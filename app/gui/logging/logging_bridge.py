from collections import deque

import loguru
from PySide6.QtCore import QObject, Signal

from app.log import log_format, logger

from .log_entry import LogEntry


class LogBridge(QObject):
    """Bridge loguru output to Qt signal with a bounded replay buffer."""

    new_entry = Signal(object)

    def __init__(self, max_entries: int = 2000) -> None:
        super().__init__()
        self._buffer: deque[LogEntry] = deque(maxlen=max_entries)
        self._sink_id: int | None = None

    @property
    def buffer(self) -> tuple[LogEntry, ...]:
        return tuple(self._buffer)

    def _log_sink(self, message: loguru.Message) -> None:
        entry = LogEntry(text=str(message).rstrip("\n"), level_no=message.record["level"].no)
        self._buffer.append(entry)
        self.new_entry.emit(entry)

    def start(self) -> None:
        if self._sink_id is not None:
            return

        self._sink_id = logger.add(
            self._log_sink,
            format=log_format,
            level="TRACE",
            colorize=True,
            diagnose=False,
            enqueue=True,
        )

    def stop(self) -> None:
        if self._sink_id is None:
            return

        logger.remove(self._sink_id)
        self._sink_id = None
