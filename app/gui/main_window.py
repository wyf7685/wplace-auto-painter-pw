from collections.abc import Callable
from typing import override

from PyQt6.QtGui import QCloseEvent, QIcon
from PyQt6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import CaptionLabel, FluentIcon, FluentWindow, PrimaryPushButton, PushButton

from app.const import APP_NAME

from .config import ConfigEditorWidget
from .i18n import tr
from .log_viewer import AnsiLogViewer


class MainWindow(FluentWindow):
    def __init__(self, icon: QIcon) -> None:
        super().__init__()
        self._allow_close = False

        self._on_start: Callable[[], None] | None = None
        self._on_stop: Callable[[], None] | None = None
        self._on_save: Callable[[], None] | None = None
        self._on_exit: Callable[[], None] | None = None

        self._status_labels: list[CaptionLabel] = []
        self._start_buttons: list[PrimaryPushButton] = []
        self._stop_buttons: list[PushButton] = []
        self._save_buttons: list[PushButton] = []
        self._exit_buttons: list[PushButton] = []

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
        layout.addWidget(self._build_tool_row())
        layout.addWidget(content)
        return page

    def _build_tool_row(self) -> QWidget:
        row_widget = QWidget(self)
        row = QHBoxLayout(row_widget)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(8)

        start_btn = PrimaryPushButton(tr("main.action.start"))
        start_btn.clicked.connect(self._handle_start)

        stop_btn = PushButton(tr("main.action.stop"))
        stop_btn.clicked.connect(self._handle_stop)
        stop_btn.setEnabled(False)

        save_btn = PushButton(tr("main.action.save_config"))
        save_btn.clicked.connect(self._handle_save)

        exit_btn = PushButton(tr("main.action.exit"))
        exit_btn.clicked.connect(self._handle_exit)

        status_label = CaptionLabel(self._format_runtime_state("stopped"))

        row.addWidget(start_btn)
        row.addWidget(stop_btn)
        row.addWidget(save_btn)
        row.addWidget(exit_btn)
        row.addStretch()
        row.addWidget(status_label)

        self._start_buttons.append(start_btn)
        self._stop_buttons.append(stop_btn)
        self._save_buttons.append(save_btn)
        self._exit_buttons.append(exit_btn)
        self._status_labels.append(status_label)

        return row_widget

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
        state_key = {
            "running": "runtime.state.running",
            "stopped": "runtime.state.stopped",
            "error": "runtime.state.error",
        }.get(state, "runtime.state.unknown")
        return tr("main.status", state=tr(state_key, state=state))

    def set_runtime_state(self, state: str) -> None:
        is_running = state == "running"
        for label in self._status_labels:
            label.setText(self._format_runtime_state(state))
        for button in self._start_buttons:
            button.setEnabled(not is_running)
        for button in self._stop_buttons:
            button.setEnabled(is_running)

    def append_log(self, line: str) -> None:
        self.log_viewer.append_line(line)

    def show_main_window(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()

    def allow_exit(self) -> None:
        self._allow_close = True

    def _handle_start(self) -> None:
        if self._on_start is None:
            return
        self._on_start()
        self.switchTo(self.logs_page)

    def _handle_stop(self) -> None:
        if self._on_stop is None:
            return
        self._on_stop()

    def _handle_save(self) -> None:
        if self._on_save is None:
            return
        self._on_save()

    def _handle_exit(self) -> None:
        if self._on_exit is None:
            return
        self._on_exit()

    @override
    def closeEvent(self, event: QCloseEvent) -> None:  # pyright: ignore[reportIncompatibleMethodOverride]
        if self._allow_close:
            super().closeEvent(event)
            return

        event.ignore()
        self.hide()
