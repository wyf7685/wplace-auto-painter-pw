import contextlib
import importlib
import sys
from typing import NoReturn

with contextlib.redirect_stdout(None):
    importlib.import_module("qfluentwidgets")

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QApplication
from qfluentwidgets import InfoBar, InfoBarPosition, Theme, setTheme

from app.config import Config
from app.const import APP_NAME, assets
from app.exception import ConfigError
from app.log import logger

from .i18n import lang, tr
from .logging import LogBridge
from .main_window import MainWindow
from .runtime import TaskRuntime
from .state import GUIState
from .tray_icon import AppTrayIcon


class Controller:
    def __init__(self) -> None:
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setStyle("Fusion")
        setTheme(Theme.AUTO)
        lang.set_language(None)
        with contextlib.suppress(Exception):
            lang.set_language(Config.load().language)

        self.icon = self._load_icon()
        self.bridge = LogBridge()
        self.bridge.start()
        self.runtime = TaskRuntime()
        self.window = MainWindow(self.icon)
        self.tray = AppTrayIcon(self.icon, parent=self.app)

        for line in self.bridge.buffer:
            self.window.append_log(line)
        self.bridge.new_line.connect(self.window.append_log)
        self.runtime.signals.state_changed.connect(self.window.set_runtime_state)
        self.runtime.signals.config_error_occurred.connect(self.handle_config_error)
        self.app.aboutToQuit.connect(self.save_gui_state)
        self.window.set_handlers(
            on_start=self.start_runtime,
            on_stop=self.stop_runtime,
            on_save=self.save_config,
            on_exit=self.exit_app,
        )
        self.tray.setToolTip(APP_NAME)
        self.tray.setup_menu(
            on_show=self.window.show_main_window,
            on_start=self.start_runtime,
            on_stop=self.stop_runtime,
            on_exit=self.exit_app,
        )

    def run(self) -> NoReturn:
        logger.info("Starting GUI")
        self.tray.show()
        self.window.show_main_window()
        exit_code = self.app.exec()
        self.tray.hide()
        self.tray.deleteLater()
        self.runtime.stop()
        self.runtime.join(timeout=10)
        self.bridge.stop()
        logger.info("GUI exited")
        sys.exit(exit_code)

    @staticmethod
    def _load_icon() -> QIcon:
        if assets.icon.is_file():
            return QIcon(str(assets.icon))

        # Fallback to a simple colored square if the icon file is missing
        pixmap = QPixmap(16, 16)
        pixmap.fill(QColor(0, 120, 215))
        return QIcon(pixmap)

    def handle_config_error(self, exc: ConfigError) -> None:
        logger.opt(exception=exc).error(f"Configuration error: {exc!r}")
        logger.info("Please turn to Config tab to fix the error and save before restart.")
        InfoBar.error(
            tr("controller.config_error.title"),
            tr("controller.config_error.content", detail=str(exc)),
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=10000,
            parent=self.window,
        )

    def start_runtime(self) -> None:
        if not self.window.config_editor.save_to_disk(show_message=False):
            InfoBar.warning(
                tr("controller.invalid_config.title"),
                tr("controller.invalid_config.content"),
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self.window,
            )
            return
        if not self.runtime.start():
            InfoBar.info(
                tr("controller.runtime.title"),
                tr("controller.runtime.already_running"),
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self.window,
            )
        self.window.goto_logs_page()

    def stop_runtime(self) -> None:
        self.runtime.stop()

    def save_config(self) -> None:
        self.window.config_editor.save_to_disk(show_message=True)

    def exit_app(self) -> None:
        self.runtime.stop()
        self.window.allow_exit()
        self.app.quit()

    def save_gui_state(self) -> None:
        self.window.update_state()
        GUIState.save()


def run_gui() -> NoReturn:
    try:
        Controller().run()
    except Exception:
        logger.opt(exception=True).critical("Unhandled exception in GUI")
        sys.exit(1)
