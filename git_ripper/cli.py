import argparse
import asyncio
import sys
from functools import partial

from .defaults import *
from .git_ripper import GitRipper
from .utils.colorlog import logger


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )
    parser.add_argument('url', nargs='*', help="repo url")
    # parser.add_argument(
    #     "-i",
    #     "--input",
    #     default="-",
    #     type=argparse.FileType(),
    #     help="input urls",
    # )
    parser.add_argument(
        "-o",
        "--output",
        default=OUTPUT_DIRECTORY,
        help="output directory",
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
    logger.setLevel(level=['INFO', 'DEBUG'][args.verbose])
    headers = dict(map(partial(str.split, sep=":"), args.header))
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
            output_directory=args.output,
            headers=headers,
            num_workers=args.workers,
            timeout=args.timeout,
            user_agent=args.agent,
        ).run(urls)
    )
