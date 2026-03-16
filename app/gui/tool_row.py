from collections.abc import Callable

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import QHBoxLayout, QWidget
from qfluentwidgets import CaptionLabel, PrimaryPushButton, PushButton

from .i18n import tr


class ToolRowWidget(QWidget):
    state_changed = pyqtSignal(str)

    def __init__(
        self,
        parent: QWidget,
        on_start: Callable[[], None],
        on_stop: Callable[[], None],
        on_save: Callable[[], None],
        on_exit: Callable[[], None],
    ) -> None:
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(8)

        self.start_btn = PrimaryPushButton(tr("main.action.start"))
        self.stop_btn = PushButton(tr("main.action.stop"))
        self.stop_btn.setEnabled(False)
        self.save_btn = PushButton(tr("main.action.save_config"))
        self.exit_btn = PushButton(tr("main.action.exit"))
        self.status_label = CaptionLabel(tr("main.status", state=tr("runtime.state.stopped")))

        self.start_btn.clicked.connect(on_start)
        self.stop_btn.clicked.connect(on_stop)
        self.save_btn.clicked.connect(on_save)
        self.exit_btn.clicked.connect(on_exit)

        layout.addWidget(self.start_btn)
        layout.addWidget(self.stop_btn)
        layout.addWidget(self.save_btn)
        layout.addWidget(self.exit_btn)
        layout.addStretch()
        layout.addWidget(self.status_label)

        self.state_changed.connect(self.set_runtime_state)

    def set_runtime_state(self, state: str) -> None:
        is_running = state == "running"
        self.start_btn.setEnabled(not is_running)
        self.stop_btn.setEnabled(is_running)
        self.status_label.setText(tr("main.status", state=tr(f"runtime.state.{state}", state=state)))
