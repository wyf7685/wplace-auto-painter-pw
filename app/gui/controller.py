import contextlib
import importlib
import sys
from pathlib import Path
from typing import NoReturn

with contextlib.redirect_stdout(None):
    importlib.import_module("qfluentwidgets")

from PySide6.QtCore import QLockFile, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import QApplication
from qfluentwidgets import InfoBar, InfoBarPosition, Theme, setTheme

from app.config import Config
from app.const import APP_NAME, DATA_DIR, REPOSITORY_RELEASES_URL, assets
from app.exception import ConfigError
from app.log import logger
from app.version import get_version_display

from .i18n import lang, tr
from .logging import LogBridge
from .main_window import MainWindow
from .runtime import TaskRuntime
from .state import GUIState
from .tray_icon import AppTrayIcon
from .update_controller import GuiUpdateController

UPDATE_CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000


class Controller:
    def __init__(self, ready_file: Path | None = None) -> None:
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setStyle("Fusion")
        self._ready_file = ready_file
        self._pending_update_install = False

        self._instance_lock = QLockFile(str(DATA_DIR / f".{APP_NAME}.lock"))
        if not self._instance_lock.tryLock(0):
            raise RuntimeError("Another application instance is already running")

        setTheme(Theme.AUTO)
        lang.set_language(None)
        with contextlib.suppress(Exception):
            lang.set_language(Config.load().language)

        self.icon = self._load_icon()
        self.bridge = LogBridge()
        self.bridge.start()
        self.runtime = TaskRuntime()
        self.updater = GuiUpdateController()
        self._update_timer = QTimer(self.app)
        self._update_timer.setInterval(UPDATE_CHECK_INTERVAL_MS)
        self._update_timer.timeout.connect(self._automatic_update_check)
        self.window = MainWindow(
            self.icon,
            on_start=self.start_runtime,
            on_stop=self.stop_runtime,
            on_save=self.save_config,
            on_update=self.handle_update_action,
            on_exit=self.exit_app,
        )
        self.tray = AppTrayIcon(self.icon, parent=self.app)

        for line in self.bridge.buffer:
            self.window.append_log(line)
        self.bridge.new_line.connect(self.window.append_log)
        self.runtime.signals.state_changed.connect(self._handle_runtime_state)
        self.runtime.signals.config_error_occurred.connect(self.handle_config_error)
        self.updater.state_changed.connect(self.window.set_update_state)
        self.updater.progress_changed.connect(self.window.set_update_progress)
        self.updater.error_occurred.connect(self._handle_update_error)
        self.updater.restart_requested.connect(self.exit_app)
        self.app.aboutToQuit.connect(self.save_gui_state)
        self.tray.setToolTip(APP_NAME)
        self.tray.setup_menu(
            on_show=self.window.show_main_window,
            on_start=self.start_runtime,
            on_stop=self.stop_runtime,
            on_exit=self.exit_app,
        )

    def run(self) -> NoReturn:
        logger.opt(colors=True).info(f"Starting GUI (version=<c>{get_version_display()}</>)")
        self.tray.show()
        self.window.show_main_window()
        self.updater.emit_current_state()
        if self._ready_file is not None:
            QTimer.singleShot(0, self._mark_update_ready)
        if self._auto_update_check_enabled():
            QTimer.singleShot(1000, self._automatic_update_check)
            self._update_timer.start()

        exit_code = self.app.exec()
        self.tray.hide()
        self.tray.deleteLater()
        self.runtime.stop()
        self.runtime.join(timeout=10)
        self.bridge.stop()
        self._instance_lock.unlock()
        logger.info("GUI exited")
        sys.exit(exit_code)

    @staticmethod
    def _load_icon() -> QIcon:
        if assets.icon.is_file():
            return QIcon(str(assets.icon))

        pixmap = QPixmap(16, 16)
        pixmap.fill(QColor(0, 120, 215))
        return QIcon(pixmap)

    @staticmethod
    def _auto_update_check_enabled() -> bool:
        try:
            return Config.load().check_update
        except Exception:
            return False

    def _automatic_update_check(self) -> None:
        if self.updater.state in {"idle", "current", "error"}:
            self.updater.check(notify_errors=False)

    def _mark_update_ready(self) -> None:
        ready_file = self._ready_file
        if ready_file is None:
            return
        try:
            ready_file.parent.mkdir(parents=True, exist_ok=True)
            ready_file.write_text("ready\n", encoding="utf-8")
        except OSError:
            logger.exception("Failed to report updated application readiness")
            self.app.exit(1)

    def _handle_runtime_state(self, state: str) -> None:
        self.window.set_runtime_state(state)
        if self._pending_update_install and state != "running":
            self._pending_update_install = False
            self.updater.install()

    def _handle_update_error(self, detail: str) -> None:
        InfoBar.error(
            tr("update.error.title"),
            tr("update.error.content", detail=detail),
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=10000,
            parent=self.window,
        )

    def handle_update_action(self) -> None:
        match self.updater.state:
            case "unsupported":
                QDesktopServices.openUrl(QUrl(REPOSITORY_RELEASES_URL))
            case "idle" | "current" | "error":
                self.updater.check(notify_errors=True)
            case "available":
                self.updater.download()
            case "ready":
                if self.runtime.is_running:
                    self._pending_update_install = True
                    self.window.set_update_state("applying", self.updater.version)
                    self.runtime.stop()
                else:
                    self.updater.install()

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


def run_gui(ready_file: Path | None = None) -> NoReturn:
    try:
        Controller(ready_file).run()
    except Exception:
        logger.opt(exception=True).critical("Unhandled exception in GUI")
        sys.exit(1)
