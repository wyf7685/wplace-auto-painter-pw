from collections.abc import Callable

from PyQt6.QtCore import QObject
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon


class AppTrayIcon(QSystemTrayIcon):
    def __init__(
        self,
        icon: QIcon,
        parent: QObject | None,
        on_show: Callable[[], None],
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        super().__init__(icon, parent)
        self._on_show = on_show
        self._on_start = on_start
        self._on_stop = on_stop
        self._on_exit = on_exit

        menu = QMenu()
        show_act = menu.addAction("Open")
        assert show_act is not None
        show_act.triggered.connect(self._on_show)

        start_act = menu.addAction("Start")
        assert start_act is not None
        start_act.triggered.connect(self._on_start)

        stop_act = menu.addAction("Stop")
        assert stop_act is not None
        stop_act.triggered.connect(self._on_stop)

        menu.addSeparator()
        exit_act = menu.addAction("Exit")
        assert exit_act is not None
        exit_act.triggered.connect(self._on_exit)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._on_show()
