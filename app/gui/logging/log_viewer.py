from collections import deque
from collections.abc import Callable

from PySide6.QtCore import Slot
from PySide6.QtGui import QFont, QTextCursor
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import BodyLabel, CheckBox, ComboBox, PushButton, TextEdit

from app.i18n import tr
from app.log import logger
from app.utils.ansi_qt import LOG_BG, iter_segments

from .log_entry import LogEntry

_MAX_BLOCK_COUNT = 5000


class AnsiLogViewer(QWidget):
    """ANSI log viewer with bounded history and numeric minimum-level filtering."""

    def __init__(self, *, latest_sequence: Callable[[], int]) -> None:
        super().__init__()
        self._latest_sequence = latest_sequence
        self._last_sequence = 0
        self._entries: deque[tuple[LogEntry, int]] = deque()
        self._history_blocks = 0
        self._minimum_level = 0

        self._text = TextEdit()
        self._text.setReadOnly(True)
        self._text.document().setMaximumBlockCount(_MAX_BLOCK_COUNT)
        self._text.setStyleSheet(f"QTextEdit {{ background-color: {LOG_BG.name()}; }}")
        font = QFont("Consolas")
        font.setPointSize(9)
        self._text.setFont(font)
        self._first_line = True

        self._level_filter = ComboBox()
        self._level_filter.addItem(tr("log.all_levels"), userData=0)
        for name in ("TRACE", "DEBUG", "INFO", "SUCCESS", "WARNING", "ERROR", "CRITICAL"):
            self._level_filter.addItem(name, userData=logger.level(name).no)
        self._level_filter.currentIndexChanged.connect(self._on_level_changed)

        self._auto_scroll = CheckBox(tr("log.auto_scroll"))
        self._auto_scroll.setChecked(True)

        clear_btn = PushButton(tr("log.clear"))
        clear_btn.clicked.connect(self.clear)

        toolbar = QHBoxLayout()
        toolbar.addWidget(BodyLabel(tr("log.minimum_level")))
        toolbar.addWidget(self._level_filter)
        toolbar.addWidget(self._auto_scroll)
        toolbar.addStretch()
        toolbar.addWidget(clear_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addLayout(toolbar)
        layout.addWidget(self._text)

    @Slot(object)
    def append_entry(self, entry: LogEntry) -> None:
        if entry.sequence <= self._last_sequence:
            return
        self._last_sequence = entry.sequence

        # Match Qt paragraph breaks without counting CRLF twice.
        blocks = (
            entry.text.count("\n") + entry.text.count("\r") - entry.text.count("\r\n") + entry.text.count("\u2029") + 1
        )
        self._entries.append((entry, blocks))
        self._history_blocks += blocks
        # Keep the newest oversized record; the document still limits its blocks.
        while self._history_blocks > _MAX_BLOCK_COUNT and len(self._entries) > 1:
            evicted, evicted_blocks = self._entries.popleft()
            self._history_blocks -= evicted_blocks
            if evicted.level_no >= self._minimum_level:
                self._remove_oldest_blocks(evicted_blocks)

        if entry.level_no < self._minimum_level:
            return

        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.beginEditBlock()
        try:
            self._insert_text(cursor, entry.text)
        finally:
            cursor.endEditBlock()
        if self._auto_scroll.isChecked():
            self._text.moveCursor(QTextCursor.MoveOperation.End)

    def _insert_text(self, cursor: QTextCursor, text: str) -> None:
        if self._first_line:
            self._first_line = False
        else:
            cursor.insertBlock()
        for segment, fmt in iter_segments(text):
            cursor.insertText(segment, fmt)

    def _remove_oldest_blocks(self, blocks: int) -> None:
        if blocks >= self._text.document().blockCount():
            self._clear_document()
            return
        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.Start)
        cursor.movePosition(QTextCursor.MoveOperation.NextBlock, QTextCursor.MoveMode.KeepAnchor, blocks)
        cursor.removeSelectedText()

    @Slot()
    def _on_level_changed(self) -> None:
        self._minimum_level = int(self._level_filter.currentData())
        self._rebuild_document()

    def _rebuild_document(self) -> None:
        scrollbar = self._text.verticalScrollBar()
        scroll_position = scrollbar.value()
        self._text.setUpdatesEnabled(False)
        self._clear_document()
        cursor = self._text.textCursor()
        cursor.beginEditBlock()
        try:
            for entry, _ in self._entries:
                if entry.level_no >= self._minimum_level:
                    self._insert_text(cursor, entry.text)
        finally:
            cursor.endEditBlock()
            self._text.setUpdatesEnabled(True)
        if self._auto_scroll.isChecked():
            self._text.moveCursor(QTextCursor.MoveOperation.End)
        else:
            scrollbar.setValue(scroll_position)

    def clear(self) -> None:
        # The bridge watermark includes events that Qt has not delivered yet.
        self._last_sequence = max(self._last_sequence, self._latest_sequence())
        self._entries.clear()
        self._history_blocks = 0
        self._clear_document()

    def _clear_document(self) -> None:
        self._text.clear()
        self._first_line = True
