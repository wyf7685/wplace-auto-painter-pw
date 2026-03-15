from collections import deque

import loguru
from PyQt6.QtCore import QObject, pyqtSignal


class LogBridge(QObject):
    """Bridge loguru output to Qt signal with a bounded replay buffer."""

    new_line = pyqtSignal(str)

    def __init__(self, max_lines: int = 2000) -> None:
        super().__init__()
        self._buffer: deque[str] = deque(maxlen=max_lines)
        self._sink_id: int | None = None

    @property
    def buffer(self) -> tuple[str, ...]:
        return tuple(self._buffer)

    def start(self) -> None:
        if self._sink_id is not None:
            return

        from app.log import log_format, log_level_filter, logger

        def _sink(message: loguru.Message) -> None:
            text = str(message).rstrip("\n")
            self._buffer.append(text)
            self.new_line.emit(text)

        self._sink_id = logger.add(
            _sink,
            format=log_format,
            filter=log_level_filter(),
            level="DEBUG",
            colorize=True,
            enqueue=True,
        )

    def stop(self) -> None:
        if self._sink_id is None:
            return

        from app.log import logger

        logger.remove(self._sink_id)
        self._sink_id = None
