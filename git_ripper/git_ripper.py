import asyncio
import os
import re
import subprocess
import typing
from asyncio import Queue
from contextlib import asynccontextmanager
from functools import cached_property
from pathlib import Path
from urllib.parse import unquote, urljoin

import httpx
from httpx._types import HeaderTypes

from .utils.colorlog import get_logger
from .utils.git import GitIndex

COMMON_BRANCH_NAMES = ['main', 'master', 'develop']
DOWNLOAD_DIRECTORY = 'output'
NUM_WORKERS = 50
TIMEOUT = 15.0
USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64)"
    " AppleWebKit/537.36 (KHTML, like Gecko)"
    " Chrome/102.0.5005.115"
    " Safari/537.36"
)


class GitRipper:
    def __init__(
        self,
        *,
        download_directory: str = DOWNLOAD_DIRECTORY,
        num_workers: int = NUM_WORKERS,
        timeout: float = TIMEOUT,
        headers: HeaderTypes | None = None,
        user_agent: str = USER_AGENT,
    ) -> None:
        self.download_directory = Path(download_directory)
        if (
            self.download_directory.exists()
            and not self.download_directory.is_dir()
        ):
            raise ValueError("download directory wrong file type")
        self.num_workers = num_workers
        self.headers = headers
        self.timeout = timeout
        self.user_agent = user_agent
        self.logger = get_logger()

    async def run(self, urls: typing.Sequence[str]) -> None:
        queue = Queue()

        for url in urls:
            url = self.normalize_git_url(url)
            self.logger.debug("git url: %s", url)
            for file in self.common_files:
                queue.put_nowait((url, file))

        # Посещенные ссылки
        seen = set()

        # Запускаем задания в фоне
        workers = [
            asyncio.create_task(self.worker(queue, seen))
            for i in range(self.num_workers)
        ]

        # Ждем пока очередь станет пустой
        await queue.join()

        # Останавливаем задания
        for w in workers:
            w.cancel()

        # self.logger.info("run `git checkout -- .` to retrieve source code!")
        self.retrieve_souce_code()

    def retrieve_souce_code(self) -> None:
        # save current working directory
        cur_dir = Path.cwd()

        for path in self.download_directory.glob('*/.git'):
            if not path.is_dir():
                self.logger.warn("file is not directory: %s", path)
                continue

            os.chdir(path.parent)

            try:
                subprocess.check_output(
                    ['git', 'checkout', '--', '.'], shell=True, text=True
                )
                self.logger.info("source retrieved: %s", path)
            except subprocess.CalledProcessError as ex:
                self.logger.error("can't retrieve source: %s", path)

        # restore working directory
        os.chdir(cur_dir)

    @asynccontextmanager
    async def get_client(self) -> typing.Iterable[httpx.AsyncClient]:
        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=False,
        ) as client:
            client.headers.setdefault("User-Agent", self.user_agent)
            yield client

    async def worker(self, queue: Queue, seen: set[str]) -> None:
        async with self.get_client() as client:
            while True:
                try:
                    url, filepath = await queue.get()
                    await self.handle_download(
                        client, url, filepath, queue, seen
                    )
                except Exception as ex:
                    self.logger.error(
                        "An unexpected error has occurred: %s", ex
                    )
                finally:
                    queue.task_done()

    async def handle_download(
        self,
        client: httpx.AsyncClient,
        base_url: str,
        filepath: str,
        queue: Queue,
        seen: set[str],
    ) -> None:
        download_url = urljoin(base_url, filepath)

        if download_url in seen:
            self.logger.debug('already seen: %s', download_url)
            return

        seen.add(download_url)

        # "https://example.org/Old%20Site/.git/index" -> "output/example.org/Old Site/.git/index"
        downloaded = self.download_directory.joinpath(
            unquote(download_url.split('://')[1])
        )

        # self.logger.debug(downloaded)

        # Скачиваем файл, если это необходимо
        if not downloaded.exists():
            try:
                async with client.stream('GET', download_url) as response:
                    response.raise_for_status()
                    downloaded.parent.mkdir(parents=True, exist_ok=True)
                    with downloaded.open('wb') as f:
                        # 64kb хватит всем (c)
                        async for chunk in response.aiter_bytes(1 << 16):
                            f.write(chunk)
                self.logger.info("file downloaded: %s", download_url)
            except:
                if downloaded.exists():
                    downloaded.unlink()
                self.logger.error("download failed: %s", download_url)
                return
        else:
            self.logger.debug('file exists: %s', downloaded)

        if filepath == 'config':
            self.logger.debug('parse config: %s', downloaded)
            with downloaded.open() as f:
                contents = f.read()
                for branch in re.findall(r'\[branch "([^"]+)"\]', contents):
                    self.logger.debug('found: %s', branch)
                    for ref in self.gen_branch_refs(branch):
                        await queue.put((base_url, ref))
        elif filepath == 'index':
            self.logger.debug('parse index: %s', downloaded)
            with downloaded.open('rb') as f:
                for entry in GitIndex(f):
                    hash = entry.sha1.hex()
                    self.logger.debug('found: %s', hash)
                    await queue.put((base_url, self.get_object_filepath(hash)))
        elif filepath == "objects/info/packs":
            self.logger.debug('parse packs: %s', downloaded)
            # Содержит строки вида "P <hex>.pack"
            with downloaded.open() as f:
                contents = f.read()
                for pack in re.findall(r'\bpack\-[a-f\d]{40}\b', contents):
                    self.logger.debug('found: %s', pack)
                    await queue.put((base_url, f"objects/pack/{pack}.idx"))
                    await queue.put((base_url, f"objects/pack/{pack}.pack"))
        elif not filepath.startswith('objects/') and filepath not in (
            'COMMIT_EDITMSG',
            'description',
            'info/exclude',
        ):
            """
            HEAD:

                ref: refs/heads/master

            packed-refs:

                # pack-refs with: peeled fully-peeled
                f30744354f9dd0966b728ea48576612c4354a64b refs/remotes/origin/1.8pre
                247d824d35e81ec96e1a8913674c97fb45dd40ae refs/remotes/origin/master
                bcc8a837055fe720579628d758b7034d6b520f2e refs/tags/1.0
                bcc8a837055fe720579628d758b7034d6b520f2e refs/tags/1.0.1
                ...
            """
            self.logger.debug("parse object hashes and refs: %s", downloaded)
            with downloaded.open() as f:
                contents = f.read()

                for item in re.findall(
                    r'\b[a-f\d]{40}\b|\brefs/\S+', contents
                ):
                    self.logger.debug('found: %s', item)
                    await queue.put(
                        (
                            base_url,
                            item
                            if item.startswith('ref')
                            else self.get_object_filepath(item),
                        )
                    )

    def get_object_filepath(self, hash: str) -> str:
        return f'objects/{hash[:2]}/{hash[2:]}'

    def normalize_git_url(self, u: str) -> str:
        u = re.sub(r'^(?!https?://)', 'http://', u, re.I)
        return urljoin(u, '.git/')

    @cached_property
    def common_files(self) -> list[str]:
        rv = [
            "COMMIT_EDITMSG",
            "HEAD",
            "config",
            "description",
            "index",
            "info/exclude",
            "logs/HEAD",
            "objects/info/packs",
            "packed-refs",
        ]

        for branch in COMMON_BRANCH_NAMES:
            rv.extend(self.gen_branch_refs(branch))

        return rv

    def gen_branch_refs(self, branch: str) -> typing.Iterable[str]:
        for prefix in '', 'logs/':
            yield f'{prefix}refs/heads/{branch}'
            yield f'{prefix}refs/remotes/origin/{branch}'
