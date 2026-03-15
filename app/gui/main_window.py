from collections.abc import Callable
from typing import override

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtGui import QCloseEvent, QIcon
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import CaptionLabel, FluentIcon, FluentWindow, PrimaryPushButton, PushButton

from app.const import APP_NAME

from .config import ConfigEditorWidget
from .i18n import tr
from .log_viewer import AnsiLogViewer


class ToolRowWidget(QWidget):
    state_changed = pyqtSignal(str)

    def __init__(
        self,
        parent: MainWindow,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_save: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.start_btn = PrimaryPushButton(tr("main.action.start"))
        self.stop_btn = PushButton(tr("main.action.stop"))
        self.stop_btn.setEnabled(False)
        self.save_btn = PushButton(tr("main.action.save_config"))
        self.exit_btn = PushButton(tr("main.action.exit"))
        self.status_label = CaptionLabel(tr("main.status", state=tr("runtime.state.stopped")))

        self.start_btn.clicked.connect(on_start)
        self.stop_btn.clicked.connect(on_stop)
        self.save_btn.clicked.connect(on_save)
        self.exit_btn.clicked.connect(on_exit)

        layout.addWidget(self.start_btn)
        layout.addWidget(self.stop_btn)
        layout.addWidget(self.save_btn)
        layout.addWidget(self.exit_btn)
        layout.addStretch()
        layout.addWidget(self.status_label)

        self.state_changed.connect(self.set_runtime_state)

    def set_runtime_state(self, state: str) -> None:
        is_running = state == "running"
        self.start_btn.setEnabled(not is_running)
        self.stop_btn.setEnabled(is_running)
        self.status_label.setText(tr("main.status", state=tr(f"runtime.state.{state}", state=state)))


class MainWindow(FluentWindow):
    def __init__(self, icon: QIcon) -> None:
        super().__init__()
        self._allow_close = False

        self._on_start: Callable[[], None] | None = None
        self._on_stop: Callable[[], None] | None = None
        self._on_save: Callable[[], None] | None = None
        self._on_exit: Callable[[], None] | None = None

        self._tool_rows: list[ToolRowWidget] = []

        self.setWindowTitle(tr("main.window_title", app_name=APP_NAME))
        self.setWindowIcon(icon)
        self.resize(1160, 760)

        self.config_editor = ConfigEditorWidget()
        self.log_viewer = AnsiLogViewer()

        self.config_page = self._build_page(self.config_editor, "ConfigPage")
        self.logs_page = self._build_page(self.log_viewer, "LogsPage")

        self.addSubInterface(self.config_page, FluentIcon.SETTING, tr("main.nav.config"))
        self.addSubInterface(self.logs_page, FluentIcon.DOCUMENT, tr("main.nav.logs"))
        self.switchTo(self.config_page)

    def _build_page(self, content: QWidget, name: str) -> QWidget:
        page = QWidget(self)
        page.setObjectName(name)
        layout = QVBoxLayout(page)
        layout.setContentsMargins(16, 12, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(self._create_tool_row())
        layout.addWidget(content)
        return page

    def _create_tool_row(self) -> ToolRowWidget:
        def handle_start() -> None:
            if self._on_start is None:
                return
            self._on_start()
            self.switchTo(self.logs_page)

        def handle_stop() -> None:
            if self._on_stop is None:
                return
            self._on_stop()

        def handle_save() -> None:
            if self._on_save is None:
                return
            self._on_save()

        def handle_exit() -> None:
            if self._on_exit is None:
                return
            self._on_exit()

        tool_row = ToolRowWidget(
            self,
            on_start=handle_start,
            on_stop=handle_stop,
            on_save=handle_save,
            on_exit=handle_exit,
        )
        self._tool_rows.append(tool_row)
        return tool_row

    def set_handlers(
        self,
        *,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_save: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_save = on_save
        self._on_exit = on_exit

    def _format_runtime_state(self, state: str) -> str:
        return tr("main.status", state=tr(f"runtime.state.{state}", state=state))

    def set_runtime_state(self, state: str) -> None:
        for tool_row in self._tool_rows:
            tool_row.state_changed.emit(state)

    def append_log(self, line: str) -> None:
        self.log_viewer.append_line(line)

    def show_main_window(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def allow_exit(self) -> None:
        self._allow_close = True

    @override
    def closeEvent(self, event: QCloseEvent) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        if self._allow_close:
            super().closeEvent(event)
            return

        event.ignore()
        self.hide()
