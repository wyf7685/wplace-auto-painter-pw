from typing import override

from PyQt6.QtGui import QCloseEvent, QFont, QTextCursor
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import CheckBox, PushButton, TextEdit

from app.utils.ansi_qt import LOG_BG, iter_segments


class AnsiLogViewer(QWidget):
    """QTextEdit-based ANSI log viewer used by the integrated GUI."""

    def __init__(self, closable: bool = False) -> None:
        super().__init__()
        self._closable = closable

        self._text = TextEdit()
        self._text.setReadOnly(True)
        if doc := self._text.document():
            doc.setMaximumBlockCount(5000)
        self._text.setStyleSheet(f"QTextEdit {{ background-color: {LOG_BG.name()}; }}")
        font = QFont("Consolas")
        font.setPointSize(9)
        self._text.setFont(font)
        self._first_line = True

        self._auto_scroll = CheckBox("Auto Scroll")
        self._auto_scroll.setChecked(True)

        clear_btn = PushButton("Clear")
        clear_btn.clicked.connect(self.clear)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._auto_scroll)
        toolbar.addStretch()
        toolbar.addWidget(clear_btn)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.addLayout(toolbar)
        layout.addWidget(self._text)

    def append_line(self, text: str) -> None:
        cursor = self._text.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        if self._first_line:
            self._first_line = False
        else:
            cursor.insertBlock()
        for segment, fmt in iter_segments(text):
            cursor.insertText(segment, fmt)
        if self._auto_scroll.isChecked():
            self._text.moveCursor(QTextCursor.MoveOperation.End)

    def clear(self) -> None:
        self._text.clear()
        self._first_line = True

    @override
    def closeEvent(self, event: QCloseEvent) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        if self._closable:
            super().closeEvent(event)
            return
        event.ignore()
        self.hide()
