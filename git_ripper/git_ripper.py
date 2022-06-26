__all__ = ('GitRipper',)

import asyncio
import cgi
import os
import re
import typing
import zlib
from concurrent.futures import Executor, ProcessPoolExecutor
from contextlib import asynccontextmanager
from functools import cached_property
from pathlib import Path
from urllib.parse import unquote, urljoin

import aiohttp

from .defaults import *
from .log import logger
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
        headers: dict[str, str] | None = None,
        user_agent: str = USER_AGENT,
        override_existing: bool = False,
        executor: Executor | None = None,
    ) -> None:
        self.output_directory = Path(output_directory)
        if (
            self.output_directory.exists()
            and not self.output_directory.is_dir()
        ):
            raise ValueError("invalid output directory!")
        self.num_workers = min(1, num_workers)
        self.headers = headers
        self.timeout = aiohttp.ClientTimeout(timeout)
        self.user_agent = user_agent
        self.override_existing = override_existing
        self.executor = executor or ProcessPoolExecutor(
            max_workers=max(os.cpu_count() * 2, 4)
        )

    async def run(self, urls: typing.Sequence[str]) -> None:
        # raise RuntimeError('foo')
        # Если размер очереди не будет ограничен, то в какой-то момент все запросы будут происходить к одному сайту
        queue = asyncio.Queue()
        normalized_urls = list(map(self.normalize_git_url, urls))
        # site1/.git/HEAD, site2/.git/HEAD, ..., site1/.git/index, ...
        for file in self.common_files:
            for url in normalized_urls:
                file_url = urljoin(url, file)
                queue.put_nowait(file_url)

        # Посещенные ссылки
        seen_urls = set()

        # Запускаем задания в фоне
        workers = [
            asyncio.create_task(self.worker(queue, seen_urls))
            for _ in range(self.num_workers)
        ]

        # Ждем пока очередь станет пустой
        await queue.join()

        # Останавливаем задания
        for _ in range(self.num_workers):
            await queue.put(None)

        for w in workers:
            await w

        # logger.info("run `git checkout -- .` to retrieve source code!")
        await self.retrieve_souce_code()

    async def worker(self, queue: asyncio.Queue, seen_urls: set[str]) -> None:
        async with self.get_session() as session:
            while True:
                try:
                    file_url = await queue.get()

                    if file_url is None:
                        break

                    if file_url in seen_urls:
                        logger.debug("already seen %s", file_url)
                        continue

                    seen_urls.add(file_url)

                    # "https://example.org/Old%20Site/.git/index" -> "output/example.org/Old Site/.git/index"
                    file_path = self.output_directory.joinpath(
                        unquote(file_url.split('://')[1])
                    )

                    if self.override_existing or not file_path.exists():
                        try:
                            await self.download_file(
                                session, file_url, file_path
                            )
                        except Exception as e:
                            logger.error(e)
                            if file_path.exists():
                                file_path.unlink()
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

    async def retrieve_souce_code(self) -> None:
        for path in self.output_directory.glob('*/.git'):
            if not path.is_dir():
                logger.warn("file is not directory: %s", path)
                continue
            try:
                cmd = f"git --git-dir='{path}' --work-tree='{path.parent}' checkout -- ."
                logger.debug("run: %r", cmd)
                proc = await asyncio.create_subprocess_shell(
                    cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdin, stderr = await proc.communicate()
                if proc.returncode == 0:
                    logger.info("source retrieved: %s", path)
                else:
                    logger.warning(stderr.decode())
            except Exception as e:
                logger.error(e)

    @asynccontextmanager
    async def get_session(self) -> typing.AsyncIterable[aiohttp.ClientSession]:
        connector = aiohttp.TCPConnector(verify_ssl=False)
        async with aiohttp.ClientSession(
            connector=connector, headers=self.headers, timeout=self.timeout
        ) as session:
            session.headers.setdefault('User-Agent', self.user_agent)
            yield session

    async def download_file(
        self, session: aiohttp.ClientSession, file_url: str, file_path: Path
    ) -> None:
        response: aiohttp.ClientResponse
        async with session.get(file_url) as response:
            response.raise_for_status()
            # TODO: есть теория, что сайтов, где `text/html` тип ответа по умолчанию море
            ct, _ = cgi.parse_header(response.headers.get('content-type', ''))
            if ct == 'text/html':
                raise ValueError()
            contents = await response.read()
            file_path.parent.mkdir(parents=True, exist_ok=True)
            with file_path.open('wb') as fp:
                fp.write(contents)

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
                    sha1_hex = entry.sha1.hex()
                    logger.debug(
                        "found: %s %s",
                        sha1_hex,
                        entry.filename.decode(errors='replace'),
                    )
                    await queue.put(
                        urljoin(git_url, self.get_object_path(sha1_hex))
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
                decoded = await asyncio.get_running_loop().run_in_executor(
                    self.executor, zlib.decompress, contents
                )
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
