from collections import deque

import loguru
from PySide6.QtCore import QObject, Signal

from app.log import log_format, log_level_filter, logger


class LogBridge(QObject):
    """Bridge loguru output to Qt signal with a bounded replay buffer."""

    new_line = Signal(str)

    def __init__(self, max_lines: int = 2000) -> None:
        super().__init__()
        self._buffer: deque[str] = deque(maxlen=max_lines)
        self._sink_id: int | None = None

    @property
    def buffer(self) -> tuple[str, ...]:
        return tuple(self._buffer)

    def _log_sink(self, message: loguru.Message) -> None:
        text = str(message).rstrip("\n")
        self._buffer.append(text)
        self.new_line.emit(text)

    def start(self) -> None:
        if self._sink_id is not None:
            return

        self._sink_id = logger.add(
            self._log_sink,
            format=log_format,
            filter=log_level_filter(),
            level="DEBUG",
            colorize=True,
            diagnose=False,
            enqueue=True,
        )

    def stop(self) -> None:
        if self._sink_id is None:
            return

        logger.remove(self._sink_id)
        self._sink_id = None
