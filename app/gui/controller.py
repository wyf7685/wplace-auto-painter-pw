import sys

from PyQt6.QtGui import QColor, QIcon, QPixmap
from PyQt6.QtWidgets import QApplication, QMessageBox
from qfluentwidgets import Theme, setTheme

from app.config import Config
from app.const import APP_NAME, assets
from app.log import logger

from .logging_bridge import LogBridge
from .main_window import MainWindow
from .runtime import RuntimeSignals, TaskRuntime
from .tray_icon import AppTrayIcon


def _load_icon() -> QIcon:
    if assets.icon.is_file():
        return QIcon(str(assets.icon))

    # Fallback to a simple colored square if the icon file is missing
    pixmap = QPixmap(16, 16)
    pixmap.fill(QColor(0, 120, 215))
    return QIcon(pixmap)


def run_gui() -> None:
    argv = [arg for arg in sys.argv if arg != "--tray"]
    app = QApplication(argv)
    app.setQuitOnLastWindowClosed(False)
    setTheme(Theme.AUTO)

    Config.set_background_mode()

    icon = _load_icon()
    bridge = LogBridge()
    bridge.start()

    runtime_signals = RuntimeSignals()
    runtime = TaskRuntime(runtime_signals)

    window = MainWindow(icon)

    for line in bridge.buffer:
        window.append_log(line)

    bridge.new_line.connect(window.append_log)
    runtime_signals.state_changed.connect(window.set_runtime_state)

    def start_runtime() -> None:
        if not window.config_editor.save_to_disk(show_message=False):
            QMessageBox.warning(window, "Config", "Config is invalid, please fix fields before start.")
            return
        if not runtime.start():
            QMessageBox.information(window, "Runtime", "Runtime is already running.")

    def stop_runtime() -> None:
        runtime.stop()

    def save_config() -> None:
        window.config_editor.save_to_disk(show_message=True)

    def exit_app() -> None:
        runtime.stop()
        window.allow_exit()
        app.quit()

    window.set_handlers(
        on_start=start_runtime,
        on_stop=stop_runtime,
        on_save=save_config,
        on_exit=exit_app,
    )

    tray = AppTrayIcon(
        icon,
        app,
        on_show=window.show_main_window,
        on_start=start_runtime,
        on_stop=stop_runtime,
        on_exit=exit_app,
    )
    tray.setToolTip(APP_NAME)
    tray.show()

    window.show()

    exit_code = app.exec()

    tray.hide()
    runtime.stop()
    runtime.join(timeout=10)
    bridge.stop()

    logger.info("GUI exited")
    sys.exit(exit_code)
