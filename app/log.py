import functools
import inspect
import logging
import re
import sys
from typing import TYPE_CHECKING

import loguru

if TYPE_CHECKING:
    from collections.abc import Callable

    from loguru import Logger, Record


logger: Logger = loguru.logger


def escape_tag(s: str) -> str:
    """用于记录带颜色日志时转义 `<tag>` 类型特殊标签

    参考: [loguru color 标签](https://loguru.readthedocs.io/en/stable/api/logger.html#color)

    参数:
        s: 需要转义的字符串
    """
    return re.sub(r"</?((?:[fb]g\s)?[^<>\s]*)>", r"\\\g<0>", s)


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


log_format = "<g>{time:HH:mm:ss}</g> [<lvl>{level}</lvl>] <c><u>{name}</u></c> | {message}"
logger.remove()


def _filter() -> Callable[[Record], bool]:
    @functools.cache
    def _level() -> int:
        from app.config import Config

        return logger.level(Config.load().log_level).no

    def filter_func(record: Record) -> bool:
        try:
            return record["level"].no >= _level()
        except Exception:
            return True

    return filter_func


if sys.stdout:
    logger.add(
        sys.stdout,
        level="DEBUG",
        diagnose=False,
        enqueue=True,
        format=log_format,
        filter=_filter(),
    )
logger.add(
    "./logs/{time:YYYY-MM-DD}.log",
    rotation="00:00",
    level="DEBUG",
    diagnose=True,
    enqueue=True,
    format=log_format,
)
