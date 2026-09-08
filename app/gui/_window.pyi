# Match upstream API names while keeping the static base platform-independent.
# ruff: noqa: N802, N803, N815

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QWidget
from qfluentwidgets import (
    FluentIconBase,
    NavigationInterface,
    NavigationItemPosition,
    NavigationTreeWidget,
)

class FluentWindow(QWidget):
    navigationInterface: NavigationInterface

    def __init__(self, parent: QWidget | None = None) -> None: ...
    def addSubInterface(
        self,
        interface: QWidget,
        icon: FluentIconBase | QIcon | str,
        text: str,
        position: NavigationItemPosition = ...,
        parent: QWidget | str | None = None,
        isTransparent: bool = False,
    ) -> NavigationTreeWidget: ...
    def switchTo(self, interface: QWidget) -> None: ...
