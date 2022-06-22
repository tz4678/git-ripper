import asyncio
import cgi
import os
import re
import subprocess
import typing
import zlib
from concurrent.futures import ProcessPoolExecutor
from contextlib import asynccontextmanager
from functools import cached_property
from pathlib import Path
from urllib.parse import unquote, urljoin

import httpx
from httpx import Response
from httpx._types import HeaderTypes

from .defaults import *
from .utils.colorlog import logger
from .utils.git import GitIndex

COMMON_BRANCH_NAMES = ['master', 'main', 'develop']
BRANCH_RE = re.compile(r'\[branch "([^"]+)"\]')
HASH_RE = re.compile(r'\b[\da-f]{40}\b')
REF_RE = re.compile(r'\bref/\S+')
HASH_OR_REF_RE = re.compile(HASH_RE.pattern + '|' + REF_RE.pattern)
PACK_HASH_RE = re.compile(r'\bpack\-[\da-f]{40}\b')
OBJECT_FILENAME_RE = re.compile(r'objects/[\da-f]{2}/[\da-f]{38}')


class GitRipper:
    def __init__(
        self,
        *,
        output_directory: str = OUTPUT_DIRECTORY,
        num_workers: int = NUM_WORKERS,
        timeout: float = TIMEOUT,
        headers: HeaderTypes | None = None,
        user_agent: str = USER_AGENT,
    ) -> None:
        self.output_directory = Path(output_directory)
        if (
            self.output_directory.exists()
            and not self.output_directory.is_dir()
        ):
            raise ValueError(
                f"{str(self.output_directory)!r} is not directory!"
            )
        self.num_workers = min(1, num_workers)
        self.headers = headers
        self.timeout = timeout
        self.user_agent = user_agent
        self.executor = ProcessPoolExecutor(max_workers=os.cpu_count() * 2 - 1)

    async def run(self, urls: typing.Sequence[str]) -> None:
        queue = asyncio.Queue()
        normalized_urls = list(map(self.normalize_git_url, urls))
        # target1/.git/HEAD
        # target2/.git/HEAD
        # ...
        # target1/.git/index
        for file in self.common_files:
            for url in normalized_urls:
                file_url = urljoin(url, file)
                logger.debug("enqueue: %s", file_url)
                queue.put_nowait(file_url)

        # Посещенные ссылки
        seen_urls = set()

        # Запускаем задания в фоне
        workers = [
            asyncio.create_task(self.worker(queue, seen_urls))
            for i in range(self.num_workers)
        ]

        # Ждем пока очередь станет пустой
        await queue.join()

        # Останавливаем задания
        for w in workers:
            w.cancel()

        # logger.info("run `git checkout -- .` to retrieve source code!")
        self.retrieve_souce_code()

    def retrieve_souce_code(self) -> None:
        # save current working directory
        cur_dir = Path.cwd()

        for path in self.output_directory.glob('*/.git'):
            if not path.is_dir():
                logger.warn("file is not directory: %s", path)
                continue

            os.chdir(path.parent)

            try:
                subprocess.check_output(
                    ['git', 'checkout', '--', '.'], shell=True, text=True
                )
                logger.info("source retrieved: %s", path)
            except subprocess.CalledProcessError as ex:
                # Command '['git', 'checkout', '--', '.']' returned non-zero exit status 1.
                logger.error("can't retrieve source: %s", path)

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

    async def worker(self, queue: asyncio.Queue, seen_urls: set[str]) -> None:
        async with self.get_client() as client:
            while True:
                try:
                    file_url = await queue.get()

                    if file_url in seen_urls:
                        logger.debug("already seen %s", file_url)
                        continue

                    seen_urls.add(file_url)

                    # "https://example.org/Old%20Site/.git/index" -> "output/example.org/Old Site/.git/index"
                    file_path = self.output_directory.joinpath(
                        unquote(file_url.split('://')[1])
                    )

                    if not file_path.exists():
                        try:
                            await self.download_file(
                                client, file_url, file_path
                            )
                        except:
                            if file_path.exists():
                                file_path.unlink()
                            logger.error("download failed: %s", file_url)
                            continue
                    else:
                        logger.debug("file exists: %s", file_path)

                    await self.parse_file(
                        file_path, self.get_git_baseurl(file_url), queue
                    )
                except Exception as ex:
                    logger.error("An unexpected error has occurred: %s", ex)
                finally:
                    queue.task_done()

    async def download_file(
        self, client: httpx.AsyncClient, file_url: str, file_path: Path
    ) -> None:
        response: Response
        async with client.stream('GET', file_url) as response:
            response.raise_for_status()
            # TODO: есть теория, что сайтов, где `text/html` тип ответа по умолчанию море
            # ct, _ = cgi.parse_header(response.headers['content-type'])
            # if ct == 'text/html':
            #     raise ValueError()
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with file_path.open('wb') as fp:
                async for chunk in response.aiter_bytes(1 << 13):
                    fp.write(chunk)
        logger.info("downloaded: %s", file_url)

    async def parse_file(
        self,
        file_path: Path,
        git_url: str,
        queue: asyncio.Queue,
    ) -> None:
        _, filename = str(file_path).split('.git/')
        if filename == 'config':
            logger.debug("parse config: %s", file_path)
            contents = file_path.read_text()
            for branch in BRANCH_RE.findall(contents):
                logger.debug('found: %s', branch)
                for ref in self.gen_branch_refs(branch):
                    await queue.put(urljoin(git_url, ref))
        elif filename == 'index':
            logger.debug("parse index: %s", file_path)
            with file_path.open('rb') as fp:
                for entry in GitIndex(fp):
                    obj = entry.sha1.hex()
                    logger.debug("found: %s", obj)
                    await queue.put(
                        urljoin(git_url, self.get_object_path(obj))
                    )
        elif filename == 'objects/info/packs':
            logger.debug("parse packs: %s", file_path)
            # Содержит строки вида "P <hex>.pack"
            contents = file_path.read_text()
            for pack in PACK_HASH_RE.findall(contents):
                logger.debug("found: %s", pack)
                await queue.put(urljoin(git_url, f'objects/pack/{pack}.idx'))
                await queue.put(urljoin(git_url, f'objects/pack/{pack}.pack'))
        elif OBJECT_FILENAME_RE.fullmatch(filename):
            logger.debug("parse object: %s", file_path)
            contents = file_path.read_bytes()
            try:
                # Очень ресурсоемкая операция, выполнение которой в ProcessPoolExecutor заметно ускоряет общую скорость
                decoded = await self.run_in_executor(zlib.decompress, contents)
            except zlib.error:
                logger.error("delete invalid object: %s", file_path)
                file_path.unlink()
                return
            if decoded[:4] == b'blob':
                logger.debug("skip blob: %s", file_path)
                return
            decoded_text = decoded.decode(errors='replace')
            for x in HASH_RE.findall(decoded_text):
                logger.debug("found: %s", x)
                await queue.put(urljoin(git_url, self.get_object_path(x)))
        else:
            logger.debug("parse: %s", file_path)
            contents = file_path.read_text()
            for x in HASH_OR_REF_RE.findall(contents):
                logger.debug("found: %s", x)
                await queue.put(
                    urljoin(
                        git_url,
                        x if x.startswith('ref') else self.get_object_path(x),
                    )
                )

    async def run_in_executor(
        self, func: typing.Callable, *args: typing.Any
    ) -> typing.Any:
        return await asyncio.get_running_loop().run_in_executor(
            self.executor, func, *args
        )

    def get_git_baseurl(self, url: str) -> str:
        return re.sub(r'(?<=\.git/).*', '', url)

    def get_object_path(self, hash: str) -> str:
        return f'objects/{hash[:2]}/{hash[2:]}'

    def normalize_git_url(self, url: str) -> str:
        url = re.sub(r'^(?!https?://)', 'http://', url, re.I)
        # без аргумента count неправильно работает
        return re.sub(r'(/\.git)?/?$', '/.git/', url, 1)

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
