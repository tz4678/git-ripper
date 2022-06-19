import argparse
import asyncio
import logging
import sys
from functools import partial

from .git_ripper import GitRipper
from .log import init_logger


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('url', nargs='*', help='urls')
    parser.add_argument(
        "-i",
        "--input",
        default="-",
        type=argparse.FileType(),
        help="input urls",
    )
    parser.add_argument(
        "-d",
        "--directory",
        "--dir",
        default="output",
        help="download directory",
    )
    parser.add_argument(
        "-H",
        "--header",
        default=[],
        nargs="*",
        help="header",
    )
    parser.add_argument(
        "--workers",
        "-w",
        default=10,
        help="number of workers",
        type=int,
    )
    parser.add_argument(
        "--timeout",
        default=5.0,
        help="client timeout",
        type=float,
    )
    # parser.add_argument(
    #     "-v",
    #     "--verbose",
    #     action="count",
    #     default=0,
    #     help="be more verbose",
    # )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="be more verbose",
    )
    # parser.add_argument(
    #     '--version', action='version', version=f'%(prog)s v{__version__}'
    # )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    # log_levels = ["WARNING", "INFO", "DEBUG"]
    # level = log_levels[min(args.verbose, len(log_levels) - 1)]
    # init_logger(level)
    init_logger(level=['INFO', 'DEBUG'][args.verbose])
    urls = list(args.url)
    if not args.input.isatty():
        urls.extend(map(str.strip, args.input))
    headers = map(partial(str.split, sep=":"), args.header)
    coro = GitRipper(
        download_directory=args.directory,
        num_workers=args.workers,
        headers=headers,
        timeout=args.timeout,
    ).run(urls)
    asyncio.run(coro)
