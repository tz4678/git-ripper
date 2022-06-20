"""Логгер, который срет в консоль всеми цветами радуги"""
import logging

from colorama import Back, Fore, init


class ColorFormatter(logging.Formatter):
    # Change this dictionary to suit your coloring needs!
    COLORS = {
        "DEBUG": Fore.BLUE,
        "INFO": Fore.GREEN,
        "WARNING": Fore.MAGENTA,
        "ERROR": Fore.RED,
        "CRITICAL": Fore.RED + Back.WHITE,
    }

    def format(self, record: logging.LogRecord) -> str:
        message = super().format(record)
        if color := self.COLORS.get(record.levelname):
            message = color + message + Fore.RESET
        return message


class ColorLogger(logging.Logger):
    def __init__(self, name: str) -> None:
        super().__init__(name, logging.WARNING)
        color_formatter = ColorFormatter("[%(levelname)s]: %(message)s")
        # stream по дефолту sys.stderr
        console = logging.StreamHandler()
        console.setFormatter(color_formatter)
        self.addHandler(console)


def get_logger() -> logging.Logger:
    return logging.getLogger("git-ripper")


def setup_logger(
    level: int | str,
) -> None:
    init(autoreset=True)
    logging.setLoggerClass(ColorLogger)
    get_logger().setLevel(level)
