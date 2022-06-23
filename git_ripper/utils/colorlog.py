import logging

from .termcolors import Back, Fore, Style


class ColorFormatter(logging.Formatter):
    COLORS = {
        'DEBUG': Fore.BLUE,
        'INFO': Fore.GREEN,
        'WARNING': Fore.YELLOW,
        'ERROR': Fore.RED,
        'CRITICAL': Fore.RED,
    }

    def format(self, record: logging.LogRecord) -> str:
        if color := self.COLORS.get(record.levelname):
            record.levelname = color + record.levelname + Style.RESET
            # TypeError: can only concatenate str (not "RuntimeError") to str
            record.msg = color + str(record.msg) + Style.RESET
        return super().format(record)


class ColorLogger(logging.Logger):
    def __init__(self, name: str) -> None:
        super().__init__(name, logging.WARNING)
        color_formatter = ColorFormatter("[%(levelname)s] - %(message)s")
        # stream по дефолту sys.stderr
        console = logging.StreamHandler()
        console.setFormatter(color_formatter)
        self.addHandler(console)
