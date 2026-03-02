"""System tray integration for wplace-auto-painter.

This module is **only imported** when tray mode is active (``--tray`` flag or
``config.tray_mode = true``).  It must not be imported in the default code path.

Architecture
------------
Main thread  : Qt event loop + QSystemTrayIcon + LogWindow
Background   : ``anyio.run(async_main)`` in a daemon ``threading.Thread``

Shutdown coordination
---------------------
Qt → anyio  : ``_stop_event.set()`` then ``QApplication.quit()``
anyio → Qt  : ``_Emitter.anyio_done`` signal → ``_request_quit()``
``run_tray`` : joins background thread (≤10 s) then ``sys.exit()``
"""

import sys
import threading
from collections import deque
from collections.abc import Callable, Coroutine
from typing import Any, override

import anyio
import anyio.to_thread
from PyQt6.QtCore import QObject, Qt, pyqtSignal
from PyQt6.QtGui import QCloseEvent, QColor, QFont, QIcon, QPixmap, QTextCursor
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QMenu,
    QPlainTextEdit,
    QPushButton,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

type AsyncMain = Callable[[], Coroutine[None, None, None]]

# ── Constants ──────────────────────────────────────────────────────────────────

_LOG_BUFFER_MAXLEN = 2000

# ── Shared state (initialised before any sink is registered) ───────────────────

_log_buffer: deque[str] = deque(maxlen=_LOG_BUFFER_MAXLEN)
_stop_event = threading.Event()


# ── Qt signal carrier ──────────────────────────────────────────────────────────


class _Emitter(QObject):
    """Signals for cross-thread communication; always used via queued connection."""

    new_log = pyqtSignal(str)  # anyio/loguru thread → Qt: a new log line
    anyio_done = pyqtSignal()  # anyio thread → Qt: async work has finished


# module-level instance; set in run_tray() before the sink is registered
_emitter: _Emitter | None = None


# ── Loguru sink (called from loguru's internal enqueue thread) ─────────────────


def _qt_sink(message: Any) -> None:
    text = str(message).rstrip("\n")
    _log_buffer.append(text)
    if _emitter is not None:
        _emitter.new_log.emit(text)


# ── Widgets ────────────────────────────────────────────────────────────────────


class LogWindow(QWidget):
    """Floating window that streams loguru output in real time.

    Closing the window hides it rather than destroying it so it can be
    re-opened from the tray icon without losing history.
    """

    def __init__(self) -> None:
        super().__init__(None, Qt.WindowType.Window)
        self.setWindowTitle("wplace-auto-painter — Logs")
        self.setWindowIcon(_load_icon())
        self.resize(960, 560)

        self._text = QPlainTextEdit()
        self._text.setReadOnly(True)
        self._text.setMaximumBlockCount(5000)
        font = QFont("Consolas")
        font.setPointSize(9)
        self._text.setFont(font)

        self._auto_scroll = QCheckBox("自动滚动")
        self._auto_scroll.setChecked(True)

        clear_btn = QPushButton("清空")
        clear_btn.clicked.connect(self._text.clear)

        toolbar = QHBoxLayout()
        toolbar.addWidget(self._auto_scroll)
        toolbar.addStretch()
        toolbar.addWidget(clear_btn)

        layout = QVBoxLayout(self)
        layout.addLayout(toolbar)
        layout.addWidget(self._text)

        # Replay log history buffered before the window was first opened
        for line in _log_buffer:
            self._text.appendPlainText(line)
        self._scroll_to_bottom()

    def append_log(self, text: str) -> None:
        self._text.appendPlainText(text)
        if self._auto_scroll.isChecked():
            self._scroll_to_bottom()

    def _scroll_to_bottom(self) -> None:
        self._text.moveCursor(QTextCursor.MoveOperation.End)

    @override
    def closeEvent(self, event: QCloseEvent) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        event.ignore()
        self.hide()


class _TrayIcon(QSystemTrayIcon):
    def __init__(self, parent: QApplication, log_window: LogWindow) -> None:
        super().__init__(_load_icon(), parent)
        self._log_window = log_window

        menu = QMenu()
        show_act = menu.addAction("显示日志")
        assert show_act is not None
        show_act.triggered.connect(self._show_logs)
        menu.addSeparator()
        quit_act = menu.addAction("退出")
        assert quit_act is not None
        quit_act.triggered.connect(_request_quit)

        self.setContextMenu(menu)
        self.setToolTip("wplace-auto-painter")
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._show_logs()

    def _show_logs(self) -> None:
        self._log_window.show()
        self._log_window.raise_()
        self._log_window.activateWindow()


def _load_icon() -> QIcon:
    from app.assets import ICON_PATH

    if ICON_PATH.is_file():
        return QIcon(str(ICON_PATH))
    # Fallback: a solid 16×16 square in the Windows accent blue
    pm = QPixmap(16, 16)
    pm.fill(QColor(0, 120, 215))
    return QIcon(pm)


# ── Quit coordination ──────────────────────────────────────────────────────────


def _request_quit() -> None:
    """Initiate a clean shutdown from the Qt main thread.

    May be called either by the user (tray menu) or by the ``anyio_done``
    signal when async work finishes on its own.
    """
    _stop_event.set()
    app = QApplication.instance()
    if app is not None:
        app.quit()


# ── Anyio background thread ────────────────────────────────────────────────────


def _anyio_thread(async_main: AsyncMain, emitter: _Emitter) -> None:
    """Thread target: run *async_main* under anyio and notify Qt when done."""

    async def _runner() -> None:
        async def _stop_waiter(scope: anyio.CancelScope) -> None:
            # Block a thread-pool thread until Qt signals "stop", then cancel.
            # abandon_on_cancel=True: if the outer scope is cancelled first
            # (e.g. async_main raised), this thread is abandoned; it will
            # unblock naturally once _stop_event is set during shutdown.
            await anyio.to_thread.run_sync(_stop_event.wait, abandon_on_cancel=True)
            scope.cancel()

        async with anyio.create_task_group() as tg:
            tg.start_soon(_stop_waiter, tg.cancel_scope)
            try:
                await async_main()
            finally:
                # async_main has returned or been cancelled; stop the waiter too
                tg.cancel_scope.cancel()

    try:
        anyio.run(_runner)
    except BaseException:  # noqa: S110
        pass
    finally:
        # Signal Qt that the async side has finished so it can quit cleanly.
        # If Qt's event loop is already gone this is a no-op.
        emitter.anyio_done.emit()


# ── Entry point ────────────────────────────────────────────────────────────────


def run_tray(async_main: AsyncMain) -> None:
    """Run the application in tray mode.

    Starts Qt on the **main thread** and *async_main* concurrently in a
    **background daemon thread** via ``anyio.run()``.  Blocks until both
    sides have shut down cleanly (or the 10-second join timeout elapses).
    """
    global _emitter

    # Remove --tray so QApplication does not see an unrecognised argument
    argv = [a for a in sys.argv if a != "--tray"]
    app = QApplication(argv)
    app.setQuitOnLastWindowClosed(False)

    # Wire up the log emitter *before* registering the sink so _qt_sink
    # can safely reference it from the moment the first log is emitted.
    emitter = _Emitter()
    _emitter = emitter

    from app.config import Config
    from app.log import log_format, logger
    from app.utils import toast

    Config.set_background_mode()
    toast.notify(
        "wplace-auto-painter",
        "应用已在后台启动，可通过托盘图标查看状态。",
    )

    logger.add(
        _qt_sink,
        format=log_format,
        level="TRACE",
        colorize=False,  # strip colour tags → clean plain text in QPlainTextEdit
        enqueue=True,
    )

    log_window = LogWindow()
    tray = _TrayIcon(app, log_window)
    emitter.new_log.connect(log_window.append_log)
    # anyio finished on its own → ask Qt to quit as well
    emitter.anyio_done.connect(_request_quit)
    tray.show()

    t = threading.Thread(
        target=_anyio_thread,
        args=(async_main, emitter),
        name="anyio-main",
        daemon=True,
    )
    t.start()

    exit_code = app.exec()

    # Qt event loop has exited.  Ensure the anyio thread also stops, then
    # wait for its cleanup (shutdown_playwright etc.) before the process exits.
    _stop_event.set()
    t.join(timeout=10)

    sys.exit(exit_code)
