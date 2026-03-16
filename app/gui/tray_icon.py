from collections.abc import Callable

from PyQt6.QtWidgets import QSystemTrayIcon
from qfluentwidgets import Action, FluentIcon, SystemTrayMenu

from .i18n import tr


class AppTrayIcon(QSystemTrayIcon):
    def setup_menu(
        self,
        on_show: Callable[[], None],
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        self._on_show = on_show

        menu = SystemTrayMenu()
        menu.addAction(show_act := Action(FluentIcon.HOME, tr("tray.open")))
        show_act.triggered.connect(on_show)
        menu.addAction(start_act := Action(FluentIcon.PLAY, tr("tray.start")))
        start_act.triggered.connect(on_start)
        menu.addAction(stop_act := Action(FluentIcon.PAUSE, tr("tray.stop")))
        stop_act.triggered.connect(on_stop)
        menu.addSeparator()
        menu.addAction(exit_act := Action(FluentIcon.CLOSE, tr("tray.exit")))
        exit_act.triggered.connect(on_exit)
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._on_show()
