import asyncio
import io
import re
import typing as t
import urllib.parse
from asyncio import Queue
from asyncio.log import logger
from pathlib import Path

import httpx

from .constants import USER_AGENT
from .log import get_logger
from .utils.git import GitIndex

# class Error(Exception):
#     pass


class GitRipper:
    # TODO: добавить еще
    KNOWN_FILES = {
        "COMMIT_EDITMSG",
        # Содержит что-то типа:
        # ref: refs/heads/master
        "HEAD",
        "config",
        "description",
        "index",
        "info/exclude",
        "logs/HEAD",
        "logs/refs/heads/develop",
        "logs/refs/heads/main",
        "logs/refs/heads/master",
        "logs/refs/remotes/origin/develop",
        "logs/refs/remotes/origin/main",
        "logs/refs/remotes/origin/master",
        "objects/info/packs",
        "packed-refs",
        "refs/heads/develop",
        # Ебаная повесточка
        "refs/heads/main",
        "refs/heads/master",
        "refs/remotes/origin/develop",
        "refs/remotes/origin/main",
        "refs/remotes/origin/master",
    }

    def __init__(
        self,
        *,
        output_directory: str = "output",
        num_workers: int = 10,
        timeout: float = 15.0,
        headers: t.Sequence[tuple[str, str]] | None = None,
    ) -> None:
        self.output_directory = Path(output_directory)
        self.num_workers = num_workers
        self.headers = headers
        self.timeout = timeout
        self.logger = get_logger()

    async def run(self, urls: t.Sequence[str]) -> None:
        url_queue = Queue()

        for url in urls:
            url = self.normalize_git_url(url)
            self.logger.debug("git url: %s", url)
            for file in self.KNOWN_FILES:
                url_queue.put_nowait((url, file))

        # Запускаем задания в фоне
        tasks = [
            asyncio.create_task(self.worker(i, url_queue))
            for i in range(self.num_workers)
        ]

        # Ждем пока очередь станет пустой
        await url_queue.join()

        # Останавливаем выполнение заданий
        for _ in range(self.num_workers):
            url_queue.put_nowait(None)

        # Ждем пока задания завершатся
        for task in tasks:
            await task

        self.logger.info("run `git checkout -- .` to retrieve source code!")

    async def worker(self, n, url_queue: Queue) -> None:
        self.logger.debug("worker-%d stared", n)

        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=False,
        ) as client:
            client.headers.setdefault("User-Agent", USER_AGENT)
            while True:
                try:
                    item = await url_queue.get()

                    if item is None:
                        break

                    git_url, filename = item

                    output_path: Path = (
                        self.output_directory
                        / git_url.replace("://", "_")
                        / filename
                    )

                    # if output_path.exists():
                    #     self.logger.info(f"file exists: %s", output_path)
                    #     continue

                    download_url = urllib.parse.urljoin(git_url, filename)

                    try:
                        response = await client.get(download_url)
                        response.raise_for_status()
                    except:
                        self.logger.warn("download failed: %s", download_url)
                        continue

                    contents = response.read()

                    output_path.parent.mkdir(parents=True, exist_ok=True)

                    with output_path.open("wb") as fp:
                        fp.write(contents)

                    self.logger.info("downloaded: %s", download_url)

                    if filename == "index":
                        buf = io.BytesIO(contents)
                        for entry in GitIndex(buf):
                            await url_queue.put(
                                (
                                    git_url,
                                    self.get_object_filename(entry.object_id),
                                )
                            )
                    elif filename == "objects/info/packs":
                        """
                        Парсим подобное содержимое:

                          P pack-c6df54b99207e470d30d09bfcb1fe48373bd6b99.pack
                          P pack-06e39ff86c69ab1fae88701ffe4959870f301585.pack
                          P pack-875d8c137bdb40f74b5d5074892e0e274423db7a.pack
                        """
                        for pack_hash in re.findall(
                            r"pack\-[a-f\d]{40}", response.text
                        ):
                            await url_queue.put(
                                (git_url, f"objects/pack/{pack_hash}.idx")
                            )
                            await url_queue.put(
                                (git_url, f"objects/pack/{pack_hash}.pack")
                            )
                    # TODO: извлекать хеши из файлов типа `packed-refs`

                except Exception as ex:
                    self.logger.warn("An unexpected error has occurred: %s", ex)
                finally:
                    url_queue.task_done()

        self.logger.debug("worker-%d finished", n)

    def get_object_filename(self, hash: str) -> str:
        return f"objects/{hash[:2]}/{hash[2:]}"

    def normalize_git_url(self, url: str) -> str:
        # https://example.org -> https://example.org/.git/
        # https://example.org/ -> https://example.org/.git/
        # https://example.org/foo -> https://example.org/.git/
        # https://example.org/foo/ -> https://example.org/foo/.git/
        if "://" not in url:
            url = f"http://{url}"
        if not url.endswith("/"):
            url += "/"
        return (
            url if url.endswith(".git/") else urllib.parse.urljoin(url, ".git/")
        )
