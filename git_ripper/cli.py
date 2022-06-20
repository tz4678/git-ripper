import argparse
import asyncio
import sys
from functools import partial

from .git_ripper import (
    DOWNLOAD_DIRECTORY,
    NUM_WORKERS,
    TIMEOUT,
    USER_AGENT,
    GitRipper,
)
from .utils.colorlog import setup_logger


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('url', nargs='*', help="url must ends with /")
    # parser.add_argument(
    #     "-i",
    #     "--input",
    #     default="-",
    #     type=argparse.FileType(),
    #     help="input urls",
    # )
    parser.add_argument(
        "-d",
        "--directory",
        "--dir",
        default=DOWNLOAD_DIRECTORY,
        help="download directory",
    )
    parser.add_argument(
        "-A",
        "--agent",
        default=USER_AGENT,
        help="client user-agent string",
    )
    parser.add_argument(
        "-H",
        "--header",
        default=[],
        nargs="*",
        help="additional client header",
    )
    parser.add_argument(
        "--workers",
        "-w",
        default=NUM_WORKERS,
        help="number of workers",
        type=int,
    )
    parser.add_argument(
        "--timeout",
        default=TIMEOUT,
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
    # setup_logger(level)
    setup_logger(level=['INFO', 'DEBUG'][args.verbose])
    headers = map(partial(str.split, sep=":"), args.header)
    urls = list(args.url)
    # Если список url пуст, то скрипт будет читать из stdin
    if not urls or not sys.stdin.isatty():
        for line in map(str.strip, sys.stdin):
            # После того как будет встречена пустая строка, чтение из stdin будет прекращено.
            # Это сделано для ручного ввода, что создпает проблему с чтением из файлов, содержащих пустые строки.
            if not line:
                break
            urls.append(line)
    asyncio.run(
        GitRipper(
            download_directory=args.directory,
            headers=headers,
            num_workers=args.workers,
            timeout=args.timeout,
            user_agent=args.agent,
        ).run(urls)
    )
