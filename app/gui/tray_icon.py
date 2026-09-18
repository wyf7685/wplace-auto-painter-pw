from collections.abc import Callable

from PySide6.QtWidgets import QSystemTrayIcon
from qfluentwidgets import Action, FluentIcon, SystemTrayMenu

from app.i18n import tr


class AppTrayIcon(QSystemTrayIcon):
    _on_show: Callable[[], None] = staticmethod(lambda: None)

    def setup_menu(
        self,
        on_show: Callable[[], None],
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        self._on_show = on_show

        menu = SystemTrayMenu()
        show_action = Action(FluentIcon.APPLICATION, tr("tray.open"))
        show_action.triggered.connect(on_show)
        menu.addAction(show_action)

        self.start_action = Action(FluentIcon.PLAY, tr("tray.start"))
        self.start_action.triggered.connect(on_start)
        menu.addAction(self.start_action)

        self.stop_action = Action(FluentIcon.PAUSE, tr("tray.stop"))
        self.stop_action.triggered.connect(on_stop)
        menu.addAction(self.stop_action)

        menu.addSeparator()
        exit_action = Action(FluentIcon.POWER_BUTTON, tr("tray.exit"))
        exit_action.triggered.connect(on_exit)
        menu.addAction(exit_action)
        self.setContextMenu(menu)
        self.set_runtime_state("stopped")
        self.activated.connect(self._on_activated)

    def set_runtime_state(self, state: str) -> None:
        self.start_action.setEnabled(state not in {"running", "stopping"})
        self.stop_action.setEnabled(state == "running")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._on_show()
