from pathlib import Path

from PySide6.QtCore import QRect, Qt
from PySide6.QtWidgets import QFileDialog, QHBoxLayout, QWidget
from qfluentwidgets import BodyLabel, InfoBar, InfoBarPosition, MessageBoxBase, PushButton, SubtitleLabel

from app.gui.i18n import tr

from .image_drop_label import ImageDropLabel


class AreaEditorDialog(MessageBoxBase):
    """Modal dialog for editing selected_area with ImageDropLabel."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        image_path: str | None,
        selected_area: tuple[int, int, int, int] | None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("area_editor.title"))
        self.widget.setMinimumWidth(800)

        self._result_area: tuple[int, int, int, int] | None = selected_area
        self._result_image_path: str | None = image_path

        title = SubtitleLabel(tr("area_editor.title"), self)
        hint = BodyLabel(tr("area_editor.hint"), self)
        # hint.setTextColor(Qt.GlobalColor.darkGray, Qt.GlobalColor.lightGray)

        self._image_label = ImageDropLabel()

        browse_btn = PushButton(tr("area_editor.browse"))
        browse_btn.clicked.connect(self._pick_image)

        sync_btn = PushButton(tr("area_editor.use_current_selection"))
        sync_btn.clicked.connect(self._sync_selection)

        clear_btn = PushButton(tr("area_editor.clear_selection"))
        clear_btn.clicked.connect(self._clear_selection)

        tools = QHBoxLayout()
        tools.addWidget(hint)
        tools.addStretch(1)
        tools.addWidget(browse_btn)
        tools.addWidget(sync_btn)
        tools.addWidget(clear_btn)
        tools.setContentsMargins(0, 10, 0, 10)

        self.viewLayout.addWidget(title)
        self.viewLayout.addLayout(tools)
        self.viewLayout.addWidget(self._image_label, 1)

        self.yesButton.setText(tr("area_editor.ok"))
        self.cancelButton.setText(tr("area_editor.cancel"))

        if image_path and Path(image_path).is_file():
            self._image_label.set_image(image_path)
            if selected_area is not None:
                self._image_label.set_selection_from_original_rect(QRect(*selected_area))

    @property
    def result_area(self) -> tuple[int, int, int, int] | None:
        return self._result_area

    @property
    def result_image_path(self) -> str | None:
        return self._result_image_path

    def _pick_image(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("area_editor.select_template_image"),
            "",
            tr("area_editor.image_filter"),
        )
        if not file_path:
            return
        self._image_label.set_image(file_path)
        self._result_image_path = file_path

    def _sync_selection(self) -> None:
        self._result_area = self._image_label.create_masked_template()

    def _clear_selection(self) -> None:
        self._result_area = None
        self._image_label.select_start = None
        self._image_label.select_end = None
        self._image_label.update()

    def validate(self) -> bool:
        if self._image_label.filepath:
            self._result_image_path = self._image_label.filepath
            self._result_area = self._image_label.create_masked_template()

        if not self._result_image_path or not Path(self._result_image_path).is_file():
            InfoBar.warning(
                title=tr("area_editor.warning.title"),
                content=tr("area_editor.warning.choose_image"),
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )
            return False

        return True
