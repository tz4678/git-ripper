import asyncio
import os
import re
import subprocess
import typing
import urllib.parse
from asyncio import Queue
from functools import cached_property
from pathlib import Path

import httpx

from .log import get_logger
from .utils.git import GitIndex

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/102.0.5005.115 Safari/537.36",
)

COMMON_BRANCHES = ['main', 'master', 'develop']

# class Error(Exception):
#     pass


class GitRipper:
    def __init__(
        self,
        *,
        download_directory: str = "output",
        num_workers: int = 10,
        timeout: float = 15.0,
        headers: typing.Sequence[tuple[str, str]] | None = None,
    ) -> None:
        self.download_directory = Path(download_directory)
        self.num_workers = num_workers
        self.headers = headers
        self.timeout = timeout
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
            asyncio.create_task(self.worker(i, queue, seen))
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
                continue

            os.chdir(path.parent)

            try:
                subprocess.check_output(
                    ['git', 'checkout', '--', '.'], shell=True, text=True
                )
                self.logger.info("source code retreived: %s", path)
            except subprocess.CalledProcessError as ex:
                # self.logger.exception(ex)
                self.logger.warn("can't retrieve source code: %s", path)

        # restore working directory
        os.chdir(cur_dir)

    async def worker(
        self, worker_num: int, queue: Queue, seen: set[str]
    ) -> None:
        self.logger.debug("worker-%d stared", worker_num)
        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=False,
        ) as client:
            client.headers.setdefault("User-Agent", USER_AGENT)
            while True:
                try:
                    git_url, filename = await queue.get()
                    await self.process_item(
                        client, git_url, filename, queue, seen
                    )
                except Exception as ex:
                    self.logger.warn("An unexpected error has occurred: %s", ex)
                finally:
                    queue.task_done()
        self.logger.debug("worker-%d finished", worker_num)

    async def process_item(
        self,
        client: httpx.AsyncClient,
        git_url: str,
        filename: str,
        queue: Queue,
        seen: set[str],
    ) -> None:
        download_url = urllib.parse.urljoin(git_url, filename)

        if download_url in seen:
            self.logger.debug('already seen: %s', download_url)
            return

        seen.add(download_url)

        downloaded = self.download_directory.joinpath(
            self.url2path(download_url)
        )

        # Скачиваем файл, если это необходимо
        if not downloaded.exists():
            try:
                downloaded.parent.mkdir(parents=True, exist_ok=True)
                with downloaded.open('wb') as f:
                    async with client.stream('GET', download_url) as r:
                        r.raise_for_status()
                        async for chunk in r.aiter_bytes(4096):
                            f.write(chunk)
                self.logger.info("downloaded: %s", download_url)
            except:
                downloaded.unlink()
                self.logger.warn("downloaded: %s", download_url)
                return
        else:
            self.logger.info('file exists: %s', downloaded)

        if filename == 'config':
            self.logger.debug('parse config: %s', downloaded)
            with downloaded.open() as f:
                contents = f.read()

                for branch in re.findall(r'\[branch "([^"]+)"\]', contents):
                    self.logger.debug('found branch: %s', branch)
                    for ref in self.get_branch_refs(branch):
                        await queue.put((git_url, ref))

            return

        if filename == 'index':
            self.logger.debug('parse index: %s', downloaded)
            with downloaded.open('rb') as f:
                for entry in GitIndex(f):
                    obj_id = entry.sha1.hex()
                    self.logger.debug('found object: %s', obj_id)
                    await queue.put((git_url, self.get_object_path(obj_id)))
            return

        if filename == "objects/info/packs":
            self.logger.debug('parse packs: %s', downloaded)
            # Содержит строки вида "P <hex>.pack"
            with downloaded.open() as f:
                contents = f.read()
                for pack in re.findall(r'\bpack\-[a-f\d]{40}\b', contents):
                    self.logger.debug('found pack object: %s', pack)
                    await queue.put((git_url, f"objects/pack/{pack}.idx"))
                    await queue.put((git_url, f"objects/pack/{pack}.pack"))
            return

        # Данные хранятся в сжатом формате (ZLIB)
        # https://git-scm.com/book/ru/v2/Git-изнутри-Объекты-Git
        if filename.startswith('objects/'):
            return

        # TODO: добавить больше исключения
        if filename in ('COMMIT_EDITMSG', 'description', 'info/exclude'):
            return

        # Ищем все что выглядит как хеши объектов
        # packed-refs
        """
        # pack-refs with: peeled fully-peeled
        f30744354f9dd0966b728ea48576612c4354a64b refs/remotes/origin/1.8pre
        247d824d35e81ec96e1a8913674c97fb45dd40ae refs/remotes/origin/master
        bcc8a837055fe720579628d758b7034d6b520f2e refs/tags/1.0
        bcc8a837055fe720579628d758b7034d6b520f2e refs/tags/1.0.1
        ...
        """
        self.logger.debug("parse object sha1's & refs: %s", downloaded)
        with downloaded.open() as f:
            contents = f.read()

            for obj in re.findall(r'\b[a-f\d]{40}\b', contents):
                self.logger.debug('found object: %s', obj)
                await queue.put((git_url, self.get_object_path(obj)))

            for ref in re.findall(r'\brefs/\S+', contents):
                self.logger.debug('found ref: %s', ref)
                await queue.put((git_url, ref))

    def url2path(self, u: str) -> str:
        sp = urllib.parse.urlsplit(u)
        return sp.netloc + sp.path

    def get_object_path(self, hash: str) -> str:
        return f'objects/{hash[:2]}/{hash[2:]}'

    def normalize_git_url(self, u: str) -> str:
        u = re.sub(r'^(?!https?://)', 'http://', u, re.I)
        return urllib.parse.urljoin(u, ".git/")

    @cached_property
    def common_files(self) -> list[str]:
        rv = [
            "COMMIT_EDITMSG",
            # Содержит что-то типа:
            # ref: refs/heads/master
            "HEAD",
            "config",
            "description",
            "index",
            "info/exclude",
            "logs/HEAD",
            "objects/info/packs",
            "packed-refs",
        ]

        for branch in COMMON_BRANCHES:
            rv += self.get_branch_refs(branch)

        return rv

    def get_branch_refs(self, branch: str) -> list[str]:
        # refs/heads/main
        # refs/remotes/origin/main
        # logs/refs/heads/main
        # logs/refs/remotes/origin/main
        rv = []
        for prefix in '', 'logs/':
            rv.extend(
                [
                    f'{prefix}refs/heads/{branch}',
                    f'{prefix}refs/remotes/origin/{branch}',
                ]
            )
        return rv
