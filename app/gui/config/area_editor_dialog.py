from pathlib import Path

from PyQt6.QtCore import QRect
from PyQt6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from .image_drop_label import ImageDropLabel


class AreaEditorDialog(QDialog):
    """Modal dialog for editing selected_area with ImageDropLabel."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        image_path: str | None,
        selected_area: tuple[int, int, int, int] | None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Selected Area")
        self.resize(980, 700)

        self._result_area: tuple[int, int, int, int] | None = selected_area
        self._result_image_path: str | None = image_path

        hint = QLabel("Left drag: select area | Right drag: pan | Wheel: zoom")

        self._image_label = ImageDropLabel()

        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._pick_image)

        sync_btn = QPushButton("Use Current Selection")
        sync_btn.clicked.connect(self._sync_selection)

        clear_btn = QPushButton("Clear Selection")
        clear_btn.clicked.connect(self._clear_selection)

        tools = QHBoxLayout()
        tools.addWidget(hint)
        tools.addStretch()
        tools.addWidget(browse_btn)
        tools.addWidget(sync_btn)
        tools.addWidget(clear_btn)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self._accept_with_validation)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(tools)
        layout.addWidget(self._image_label)
        layout.addWidget(buttons)

        if image_path and Path(image_path).is_file():
            self._image_label.set_image(image_path)
            if selected_area is not None:
                self._image_label.setSelectionFromOriginalRect(QRect(*selected_area))

    @property
    def result_area(self) -> tuple[int, int, int, int] | None:
        return self._result_area

    @property
    def result_image_path(self) -> str | None:
        return self._result_image_path

    def _pick_image(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "Select template image",
            "",
            "Images (*.png *.jpg *.jpeg *.bmp)",
        )
        if not file_path:
            return
        self._image_label.set_image(file_path)
        self._result_image_path = file_path

    def _sync_selection(self) -> None:
        self._result_area = self._image_label.create_masked_template()

    def _clear_selection(self) -> None:
        self._result_area = None

    def _accept_with_validation(self) -> None:
        if self._image_label.filepath:
            self._result_image_path = self._image_label.filepath
            self._result_area = self._image_label.create_masked_template()

        if not self._result_image_path or not Path(self._result_image_path).is_file():
            QMessageBox.warning(self, "Area Editor", "Please choose an image first.")
            return

        self.accept()
