from collections.abc import Callable
from typing import override

from PySide6.QtCore import QPoint
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget
from qfluentwidgets import FluentIcon, FluentWindow

from app.const import APP_NAME

from .config import ConfigEditorWidget
from .i18n import tr
from .logging import AnsiLogViewer
from .state import GUIState
from .tool_row import ToolRowWidget


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
        self.navigationInterface.setExpandWidth(160)

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
        tool_row = ToolRowWidget(
            self,
            on_start=self._handle_start,
            on_stop=self._handle_stop,
            on_save=self._handle_save,
            on_exit=self._handle_exit,
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

    def _handle_start(self) -> None:
        if self._on_start is None:
            return
        self._on_start()

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

    def set_runtime_state(self, state: str) -> None:
        for tool_row in self._tool_rows:
            tool_row.state_changed.emit(state)

    def append_log(self, line: str) -> None:
        self.log_viewer.append_line(line)

    def goto_logs_page(self) -> None:
        self.switchTo(self.logs_page)

    def _move_to_screen_center(self) -> None:
        geometry = self.screen().availableGeometry()
        frame = self.frameGeometry()
        frame.moveCenter(geometry.center())
        self.move(frame.topLeft())

    @staticmethod
    def _point_on_visible_screen(point: QPoint) -> bool:
        return any(screen.availableGeometry().contains(point) for screen in QApplication.screens())

    def _load_window_properties(self) -> None:
        state = GUIState.load().main_window

        if (window_size := state.size_value) is not None and window_size.width() > 200 and window_size.height() > 120:
            self.resize(window_size)

        if (point := state.top_left_point) is not None and self._point_on_visible_screen(point):
            self.move(point)
        else:
            self._move_to_screen_center()

    def show_main_window(self) -> None:
        self._load_window_properties()
        self.show()
        self.raise_()
        self.activateWindow()

    def allow_exit(self) -> None:
        self._allow_close = True

    def update_state(self) -> None:
        state = GUIState.load().main_window
        state.top_left_point = self.pos()
        state.size_value = self.size()

    @override
    def closeEvent(self, event: QCloseEvent) -> None:
        if self._allow_close:
            super().closeEvent(event)
            return

        event.ignore()
        self.hide()
