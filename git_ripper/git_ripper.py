import asyncio
import io
import typing as t
import urllib.parse
from asyncio import Queue
from pathlib import Path

import httpx

from .constants import USER_AGENT
from .log import get_logger


class GitRipper:
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
        # self.log.debug("debug message")
        # self.log.critical("an unexpeced error has occurred")
        tasks = Queue()
        for url in self.normalize_urls(urls):
            tasks.put_nowait(("parse_index", url))
        workers = [self.worker(tasks) for _ in range(self.num_workers)]
        await asyncio.gather(*workers)

    async def worker(self):
        async with httpx.AsyncClient(
            headers=self.headers,
            timeout=self.timeout,
            follow_redirects=False,
        ) as client:
            client.headers.setdefault("User-Agent", USER_AGENT)

    def normalize_urls(self, urls: t.Sequence[str]) -> t.Iterable[str]:
        for url in urls:
            if "://" not in url:
                url = "https://{url}"
            # http://example.org -> http://example.org/.git
            # http://example.org/ -> http://example.org/.git
            # http://example.org/foo -> http://example.org/.git
            # http://example.org/foo/ -> http://example.org/foo/.git
            yield urllib.parse.urljoin(url, ".git")
