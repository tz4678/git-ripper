import logging

from colorama import Back, Fore, init


class ColorFormatter(logging.Formatter):
    # Change this dictionary to suit your coloring needs!
    COLORS = {
        "DEBUG": Fore.BLUE,
        "INFO": Fore.GREEN,
        "WARNING": Fore.RED,
        "ERROR": Fore.RED + Back.WHITE,
        "CRITICAL": Fore.RED + Back.WHITE,
    }

    def format(self, record):
        color = self.COLORS.get(record.levelname)
        if color:
            # record.name = color + record.name
            record.levelname = color + record.levelname
            record.msg = color + record.msg
        return logging.Formatter.format(self, record)


class ColorLogger(logging.Logger):
    def __init__(self, name):
        super().__init__(name, logging.WARNING)
        color_formatter = ColorFormatter("%(levelname)s - %(message)s")
        console = logging.StreamHandler()
        console.setFormatter(color_formatter)
        self.addHandler(console)


def get_logger() -> logging.Logger:
    return logging.getLogger("git-ripper")


def setup_logger(level: int | str) -> None:
    init(autoreset=True)
    logging.setLoggerClass(ColorLogger)
    get_logger().setLevel(level)
