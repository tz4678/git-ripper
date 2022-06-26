import logging

from .utils.logging import ColoredFormatter

logger = logging.getLogger(__name__)
console = logging.StreamHandler()
# При форматировании цвета используются только при выводе в консоль
formatter = [logging.Formatter, ColoredFormatter][console.stream.isatty()]("%(levelname)-8s - %(message)s")
console.setFormatter(formatter)
logger.addHandler(console)
