import contextlib
import sys

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import QApplication
from qfluentwidgets import InfoBar, InfoBarPosition, Theme, setTheme

from app.config import Config
from app.const import APP_NAME, assets
from app.exception import ConfigError
from app.log import logger

from .i18n import lang, tr
from .logging import LogBridge
from .main_window import MainWindow
from .runtime import RuntimeSignals, TaskRuntime
from .state import GUIState
from .tray_icon import AppTrayIcon


def _load_icon() -> QIcon:
    if assets.icon.is_file():
        return QIcon(str(assets.icon))

    # Fallback to a simple colored square if the icon file is missing
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor(0, 120, 215))
    return QIcon(pixmap)


def run_gui() -> None:
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    setTheme(Theme.AUTO)
    lang.set_language(None)
    with contextlib.suppress(Exception):
        lang.set_language(Config.load().language)

    bridge = LogBridge()
    bridge.start()

    runtime_signals = RuntimeSignals()
    runtime = TaskRuntime(runtime_signals)

    window = MainWindow(_load_icon())

    for line in bridge.buffer:
        window.append_log(line)

    bridge.new_line.connect(window.append_log)

    def handle_config_error(exc: ConfigError) -> None:
        logger.opt(exception=exc).error(f"Configuration error: {exc!r}")
        logger.info("Please turn to Config tab to fix the error and save before restart.")
        InfoBar.error(
            tr("controller.config_error.title"),
            tr("controller.config_error.content", detail=str(exc)),
            orient=Qt.Orientation.Horizontal,
            position=InfoBarPosition.TOP,
            duration=10000,
            parent=window,
        )

    runtime_signals.state_changed.connect(window.set_runtime_state)
    runtime_signals.config_error_occurred.connect(handle_config_error)

    def start_runtime() -> None:
        if not window.config_editor.save_to_disk(show_message=False):
            InfoBar.warning(
                tr("controller.invalid_config.title"),
                tr("controller.invalid_config.content"),
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=window,
            )
            return
        if not runtime.start():
            InfoBar.info(
                tr("controller.runtime.title"),
                tr("controller.runtime.already_running"),
                orient=Qt.Orientation.Horizontal,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=window,
            )

    def stop_runtime() -> None:
        runtime.stop()

    def save_config() -> None:
        window.config_editor.save_to_disk(show_message=True)

    def exit_app() -> None:
        runtime.stop()
        window.allow_exit()
        app.quit()

    def save_gui_state() -> None:
        window.update_state()
        GUIState.save()

    app.aboutToQuit.connect(save_gui_state)

    window.set_handlers(
        on_start=start_runtime,
        on_stop=stop_runtime,
        on_save=save_config,
        on_exit=exit_app,
    )

    tray = AppTrayIcon(
        _load_icon(),
        app,
        on_show=window.show_main_window,
        on_start=start_runtime,
        on_stop=stop_runtime,
        on_exit=exit_app,
    )
    tray.setToolTip(APP_NAME)
    tray.show()

    window.show_main_window()

    exit_code = app.exec()

    tray.hide()
    tray.deleteLater()
    runtime.stop()
    runtime.join(timeout=10)
    bridge.stop()

    logger.info("GUI exited")
    sys.exit(exit_code)
