import argparse
import asyncio
import sys
from functools import partial

from .git_ripper import GitRipper
from .log import setup_logger


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "-i",
        "--input",
        default=sys.stdin,
        type=argparse.FileType("r"),
        help="input urls",
    )
    parser.add_argument(
        "-o",
        "--output",
        default="output",
        help="output directory",
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
    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="be more verbose",
    )
    # parser.add_argument(
    #     '--version', action='version', version=f'%(prog)s v{__version__}'
    # )
    return parser.parse_args(argv)


def main() -> None:
    args = parse_args()
    log_levels = ["WARNING", "INFO", "DEBUG"]
    level = log_levels[min(args.verbose, len(log_levels) - 1)]
    setup_logger(level=level)
    urls = map(str.strip, args.input)
    headers = map(partial(str.split, sep=":"), args.header)
    git_ripper = GitRipper(
        output_directory=args.output,
        num_workers=args.workers,
        headers=headers,
        timeout=args.timeout,
    )
    asyncio.run(git_ripper.run(urls))
