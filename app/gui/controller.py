import contextlib
import importlib
import sys
from pathlib import Path
from typing import NoReturn

with contextlib.redirect_stdout(None):
    importlib.import_module("qfluentwidgets")

from PySide6.QtCore import QLockFile, Qt, QTimer, QUrl
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox, QSystemTrayIcon
from qfluentwidgets import InfoBar, InfoBarPosition, Theme, setTheme

from app.config import Config
from app.const import APP_NAME, DATA_DIR, REPOSITORY_RELEASES_URL, assets
from app.exception import ConfigError
from app.i18n import tr
from app.log import logger
from app.version import get_version_display

from .logging import LogBridge
from .main_window import MainWindow
from .runtime import TaskRuntime
from .state import GUIState
from .tray_icon import AppTrayIcon
from .update_controller import GuiUpdateController

UPDATE_CHECK_INTERVAL_MS = 6 * 60 * 60 * 1000


class _ApplicationAlreadyRunning(RuntimeError):
    pass


class Controller:
    def __init__(self, ready_file: Path | None = None) -> None:
        self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)
        self.app.setStyle("Fusion")
        self._ready_file = ready_file
        self._tray_hint_shown = False
        self._update_exit_preapproved = False

        self._instance_lock = QLockFile(str(DATA_DIR / f".{APP_NAME}.lock"))
        if not self._instance_lock.tryLock(0):
            QMessageBox.information(None, APP_NAME, tr("controller.already_running"))
            raise _ApplicationAlreadyRunning

        setTheme(Theme.AUTO)

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
        self._tray_available = QSystemTrayIcon.isSystemTrayAvailable()
        self.window.set_close_to_tray(self._tray_available)
        self.window.hidden_to_tray.connect(self._show_tray_hint)

        for line in self.bridge.buffer:
            self.window.append_log(line)
        self.bridge.new_line.connect(self.window.append_log)
        self.runtime.signals.state_changed.connect(self._handle_runtime_state)
        self.runtime.signals.config_error_occurred.connect(self.handle_config_error)
        self.runtime.signals.user_failed.connect(self._handle_user_failure)
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
        if self._tray_available:
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

    @staticmethod
    def _desktop_notifications_enabled() -> bool:
        try:
            return not Config.load().disable_notifications
        except Exception:
            return True

    def _show_tray_message(
        self,
        message: str,
        icon: QSystemTrayIcon.MessageIcon,
        timeout: int,
    ) -> bool:
        if not self._tray_available or not self._desktop_notifications_enabled():
            return False
        self.tray.showMessage(APP_NAME, message, icon, timeout)
        return True

    def _handle_runtime_state(self, state: str) -> None:
        self.window.set_runtime_state(state)
        self.tray.set_runtime_state(state)
        if state == "error" and not self.window.isVisible():
            self._show_tray_message(
                tr("controller.runtime.failed"),
                QSystemTrayIcon.MessageIcon.Warning,
                10000,
            )

    def _handle_user_failure(self, identifier: str) -> None:
        message = tr("controller.runtime.user_failed", identifier=identifier)
        if not self.window.isVisible():
            self._show_tray_message(
                message,
                QSystemTrayIcon.MessageIcon.Warning,
                10000,
            )
            return

        InfoBar.warning(
            tr("controller.runtime.title"),
            message,
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=10000,
            parent=self.window,
        )

    def _show_tray_hint(self) -> None:
        if self._tray_hint_shown:
            return
        self._tray_hint_shown = self._show_tray_message(
            tr("tray.background_hint"),
            QSystemTrayIcon.MessageIcon.Information,
            5000,
        )

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
                    InfoBar.warning(
                        tr("controller.update_blocked.title"),
                        tr("controller.update_blocked.content"),
                        orient=Qt.Orientation.Horizontal,
                        position=InfoBarPosition.TOP,
                        duration=5000,
                        parent=self.window,
                    )
                    return
                self._install_update()

    def _install_update(self) -> None:
        if not self._confirm_unsaved_changes():
            self.updater.emit_current_state()
            return

        self._update_exit_preapproved = True
        self.updater.install()
        if self.updater.state != "applying":
            self._update_exit_preapproved = False

    def handle_config_error(self, exc: ConfigError) -> None:
        logger.opt(exception=exc).error(f"Configuration error: {exc!r}")
        logger.info("Please turn to Config tab to fix the error and save before restart.")
        if not self.window.isVisible():
            self.window.show_main_window()
        self.window.goto_config_page()
        InfoBar.error(
            tr("controller.config_error.title"),
            tr("controller.config_error.content", detail=str(exc)),
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=10000,
            parent=self.window,
        )

    def start_runtime(self) -> None:
        result = self.window.config_editor.save_to_disk(show_message=False)
        if not result.success:
            if not self.window.isVisible():
                self.window.show_main_window()
            self.window.goto_config_page()
            InfoBar.warning(
                tr("controller.invalid_config.title"),
                result.error or tr("controller.invalid_config.content"),
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=-1,
                parent=self.window,
            )
            self.window.config_editor.focus_save_error(result)
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
        if not self.runtime.is_running:
            return
        self.window.set_runtime_state("stopping")
        self.tray.set_runtime_state("stopping")
        self.runtime.stop()

    def save_config(self) -> None:
        self.window.config_editor.save_to_disk(show_message=True)

    def _confirm_unsaved_changes(self) -> bool:
        editor = self.window.config_editor
        if not editor.has_unsaved_changes():
            return True

        self.window.show_main_window()
        self.window.goto_config_page()
        choice = QMessageBox.question(
            self.window,
            tr("config.unsaved.title"),
            tr("config.unsaved.content"),
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Save,
        )
        if choice == QMessageBox.StandardButton.Cancel:
            return False
        if choice == QMessageBox.StandardButton.Save:
            result = editor.save_to_disk(show_message=True)
            if not result.success:
                editor.focus_save_error(result)
                return False
        return True

    def exit_app(self) -> None:
        if self._update_exit_preapproved:
            self._update_exit_preapproved = False
        elif not self._confirm_unsaved_changes():
            return

        self.runtime.stop()
        self.window.allow_exit()
        self.app.quit()

    def save_gui_state(self) -> None:
        self.window.update_state()
        GUIState.save()


def run_gui(ready_file: Path | None = None) -> NoReturn:
    try:
        Controller(ready_file).run()
    except _ApplicationAlreadyRunning:
        sys.exit(0)
    except Exception:
        logger.opt(exception=True).critical("Unhandled exception in GUI")
        sys.exit(1)
