import inspect
import logging
import logging.config
import sys
from typing import TYPE_CHECKING

import loguru

if TYPE_CHECKING:
    from loguru import Logger, Record

logger: Logger = loguru.logger


# https://loguru.readthedocs.io/en/stable/overview.html#entirely-compatible-with-standard-logging
class LoguruHandler(logging.Handler):  # pragma: no cover
    """logging 与 loguru 之间的桥梁，将 logging 的日志转发到 loguru。"""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        frame, depth = inspect.currentframe(), 0
        while frame and (depth == 0 or frame.f_code.co_filename == logging.__file__):
            frame = frame.f_back
            depth += 1

        logger.opt(depth=depth, exception=record.exc_info).log(level, record.getMessage())


LOGGING_CONFIG = {
    "version": 1,
    "disable_existing_loggers": False,
    "handlers": {"default": {"class": "app.log.LoguruHandler"}},
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.error": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "uvicorn.access": {
            "handlers": ["default"],
            "level": "INFO",
            "propagate": False,
        },
        "httpx": {"handlers": ["default"], "level": "INFO", "propagate": False},
    },
}


log_format = "<g>{time:HH:mm:ss}</g> [<lvl>{level}</lvl>] <c><u>{name}</u></c> | {message}"
logger.remove()
logger_id_console = logger.add(
    sys.stdout,
    level="DEBUG",
    diagnose=False,
    enqueue=True,
    format=log_format,
)
logger_id_file = logger.add(
    "./logs/{time:YYYY-MM-DD}.log",
    rotation="00:00",
    level="DEBUG",
    diagnose=True,
    enqueue=True,
    format=log_format,
)

_HIDDEN_NAMES = ("uvicorn", "starlette", "httpx")


def _hidden_upsteam(record: Record) -> None:
    if (name := record["name"]) is None:
        return

    for hidden_name in _HIDDEN_NAMES:
        if name.startswith(hidden_name):
            record["name"] = hidden_name
            return


logger.configure(patcher=_hidden_upsteam)


def configure_logging() -> None:
    """配置日志记录器。"""
    logging.config.dictConfig(LOGGING_CONFIG)
