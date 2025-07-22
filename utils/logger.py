import sys
import os
import logging
from logging.handlers import RotatingFileHandler
from typing import Union
from datetime import datetime, timezone, timedelta

from utils.config import TIMEZONE_OFFSET

_RESET = "\x1b[0m"
_LEVEL_COLOURS = {
    logging.DEBUG: "\x1b[36m",             # cyan
    logging.INFO: "\x1b[97m",              # white
    logging.WARNING: "\x1b[33m",           # yellow
    logging.ERROR: "\x1b[31m",             # red
    logging.CRITICAL: "\x1b[41m\x1b[97m",  # white on red bg
}

DEFAULT_FORMAT = "%(asctime)s [%(levelname)s] %(message)s"
DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"
DEFAULT_QUIET_LIBS: list[str] = [
    "aiogram",
    "asyncio",
    "docker",
    "httpx",
    "urllib3",
]


class ColourLocalTimeFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        colour = _LEVEL_COLOURS.get(record.levelno, "")
        message = super().format(record)
        return f"{colour}{message}{_RESET}"

    def formatTime(self, record, datefmt=None):
        local_time = datetime.fromtimestamp(record.created).astimezone(tz=timezone(timedelta(hours=TIMEZONE_OFFSET)))
        return local_time.strftime(datefmt or DEFAULT_DATEFMT)


def setup_logging(
    level: int = logging.INFO,
    *,
    log_to_file: bool = False,
    filename: str = "./app.log",
    max_bytes: int = 100_000_000,   # 100 MB
    backup_count: int = 4
) -> None:
    """
    Инициализирует логирование.

    Parameters
    ----------
    log_to_file        – включить/выключить запись в файл
    filename           – путь к файлу логов
    max_bytes          – порог размера (байт) для ротации
    backup_count       – сколько «старых» файлов хранить
    """

    root = logging.getLogger()

    console = None
    if not root.handlers:
        console = logging.StreamHandler(sys.stdout)
        root.addHandler(console)
    else:
        for h in root.handlers:
            if isinstance(h, logging.StreamHandler):
                console = h

    if console is not None:
        console.setFormatter(ColourLocalTimeFormatter(DEFAULT_FORMAT, DEFAULT_DATEFMT))

    if log_to_file and not any(isinstance(h, RotatingFileHandler) for h in root.handlers):
        os.makedirs(os.path.dirname(filename), exist_ok=True)

        file_handler = RotatingFileHandler(
            filename,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(ColourLocalTimeFormatter(DEFAULT_FORMAT, DEFAULT_DATEFMT))
        root.addHandler(file_handler)

    root.setLevel(level)

    for lib in DEFAULT_QUIET_LIBS:
        logging.getLogger(lib).setLevel(logging.WARNING)


def get_logger(name: Union[str, None] = None) -> logging.Logger:
    return logging.getLogger(name)
