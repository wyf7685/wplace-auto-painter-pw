from collections import deque
from collections.abc import Callable
from threading import Lock

import loguru
from PySide6.QtCore import QObject, Qt, Signal

from app.log import log_format, logger

from .log_entry import LogEntry


class LogBridge(QObject):
    """Bridge loguru output to Qt signal with a bounded replay buffer."""

    new_entry = Signal(object)

    def __init__(self, max_entries: int = 2000) -> None:
        super().__init__()
        self._lock = Lock()
        self._sequence = 0
        self._buffer: deque[LogEntry] = deque(maxlen=max_entries)
        self._sink_id: int | None = None

    @property
    def buffer(self) -> tuple[LogEntry, ...]:
        with self._lock:
            return tuple(self._buffer)

    def latest_sequence(self) -> int:
        with self._lock:
            return self._sequence

    def connect_receiver(self, receiver: Callable[[LogEntry], None]) -> None:
        """Subscribe before replay; the GUI receiver deduplicates by sequence."""
        self.new_entry.connect(receiver, Qt.ConnectionType.QueuedConnection)
        for entry in self.buffer:
            receiver(entry)

    def _log_sink(self, message: loguru.Message) -> None:
        text = str(message).rstrip("\n")
        with self._lock:
            self._sequence += 1
            entry = LogEntry(text=text, level_no=message.record["level"].no, sequence=self._sequence)
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
