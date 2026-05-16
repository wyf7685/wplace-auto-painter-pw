import weakref
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFileDialog, QFormLayout, QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    CheckBox,
    ComboBox,
    ElevatedCardWidget,
    InfoBar,
    LineEdit,
    PushButton,
    SmoothScrollArea,
    SpinBox,
    StrongBodyLabel,
    TextEdit,
)

from app.gui.i18n import tr

from .area_editor_dialog import AreaEditorDialog
from .preferred_colors import PreferredColorsEditor
from .user_draft import format_selected_area, parse_selected_area, resolve_template_image

if TYPE_CHECKING:
    from .editor import ConfigEditorWidget


class UserDetailCard(ElevatedCardWidget):
    user_loaded = Signal(dict)

    def __init__(self, parent: ConfigEditorWidget) -> None:
        super().__init__(parent)
        self._editor_ref = weakref.ref(parent)

        self._build_widgets()
        self._build_layout()
        self.user_loaded.connect(self.load_user)

    def _build_widgets(self) -> None:
        self.identifier_edit = LineEdit()
        self.identifier_edit.setPlaceholderText(tr("config.placeholder.identifier"))

        self.token_edit = TextEdit()
        self.token_edit.setPlaceholderText(tr("config.placeholder.token"))
        self.token_edit.setFixedHeight(80)

        self.cf_clearance_edit = TextEdit()
        self.cf_clearance_edit.setPlaceholderText(tr("config.placeholder.cf_clearance"))
        self.cf_clearance_edit.setFixedHeight(60)

        self.file_id_edit = LineEdit()
        self.file_id_edit.setPlaceholderText(tr("config.placeholder.file_id"))

        self.coords_edit = LineEdit()
        self.coords_edit.setPlaceholderText(tr("config.placeholder.coords"))

        self.template_source_edit = LineEdit()
        self.template_source_edit.setPlaceholderText(tr("config.placeholder.template_source"))
        self.template_source_btn = PushButton(tr("config.template_source.browse"))
        self.template_source_btn.clicked.connect(self._pick_template_source)

        self.selected_area_edit = LineEdit()
        self.selected_area_edit.setPlaceholderText(tr("config.placeholder.selected_area"))
        self.edit_area_btn = PushButton(tr("config.selected_area.edit"))
        self.edit_area_btn.clicked.connect(self._open_area_editor)

        self.preferred_colors_editor = PreferredColorsEditor()

        self.min_charges_spin = SpinBox()
        self.min_charges_spin.setRange(1, 1_000_000)
        self.min_charges_spin.setValue(30)

        self.max_charges_spin = SpinBox()
        self.max_enable_cb = CheckBox(tr("config.max_enable"))
        self.max_enable_cb.toggled.connect(self.max_charges_spin.setEnabled)
        self.max_charges_spin.setRange(1, 1_000_000)
        self.max_charges_spin.setEnabled(False)

        self.auto_purchase_cb = ComboBox()
        self._auto_purchase_values = ["none", "max_charges", "charges"]
        self._auto_purchase_index = {value: index for index, value in enumerate(self._auto_purchase_values)}
        self.auto_purchase_cb.addItems(
            [
                tr("config.auto_purchase.none"),
                tr("config.auto_purchase.max_charges"),
                tr("config.auto_purchase.charges"),
            ]
        )
        self.auto_purchase_cb.currentIndexChanged.connect(self._sync_auto_purchase_fields)

        self.auto_target_spin = SpinBox()
        self.auto_target_spin.setRange(0, 1_000_000)

        self.auto_retain_spin = SpinBox()
        self.auto_retain_spin.setRange(0, 1_000_000_000)

    @property
    def editor(self) -> ConfigEditorWidget:
        editor = self._editor_ref()
        if editor is None:
            raise RuntimeError("Editor reference lost")
        return editor

    def _build_layout(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        layout.addWidget(StrongBodyLabel(tr("config.user_profile.title")))

        form_host = QWidget(self)
        form_host.setObjectName("userProfileFormHost")
        form = QFormLayout(form_host)
        form.setFormAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(12)
        form.setContentsMargins(4, 4, 8, 8)

        form.addRow(tr("config.field.identifier"), self.identifier_edit)
        form.addRow(tr("config.field.token"), self.token_edit)
        form.addRow(tr("config.field.cf_clearance"), self.cf_clearance_edit)
        form.addRow(tr("config.field.template_file_id"), self.file_id_edit)
        form.addRow(tr("config.field.template_coords"), self.coords_edit)

        source_row = QHBoxLayout()
        source_row.addWidget(self.template_source_edit)
        source_row.addWidget(self.template_source_btn)
        form.addRow(tr("config.field.template_source"), source_row)

        selected_area_row = QHBoxLayout()
        selected_area_row.addWidget(self.selected_area_edit)
        selected_area_row.addWidget(self.edit_area_btn)
        form.addRow(tr("config.field.selected_area"), selected_area_row)

        form.addRow(tr("config.field.preferred_colors"), self.preferred_colors_editor)
        form.addRow(tr("config.field.min_paint_charges"), self.min_charges_spin)

        max_row = QHBoxLayout()
        max_row.addWidget(self.max_enable_cb)
        max_row.addWidget(self.max_charges_spin)
        max_row.addStretch()
        form.addRow(tr("config.field.max_paint_charges"), max_row)

        form.addRow(tr("config.field.auto_purchase"), self.auto_purchase_cb)
        form.addRow(tr("config.field.auto_target_max"), self.auto_target_spin)
        form.addRow(tr("config.field.auto_retain_droplets"), self.auto_retain_spin)

        scroll = SmoothScrollArea(self)
        scroll.setObjectName("userProfileScroll")
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        if scroll_viewport := scroll.viewport():
            scroll_viewport.setObjectName("userProfileViewport")
        scroll.setStyleSheet(
            "QScrollArea#userProfileScroll { background: transparent; border: none; }"
            "QWidget#userProfileViewport { background: transparent; }"
            "QWidget#userProfileFormHost { background: transparent; }"
        )
        scroll.setWidget(form_host)

        layout.addWidget(scroll, stretch=1)

    def _pick_template_source(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("config.template_dialog.title"),
            "",
            tr("config.template_dialog.filter"),
        )
        if file_path:
            self.template_source_edit.setText(file_path)

    def _current_auto_purchase_value(self) -> str:
        index = self.auto_purchase_cb.currentIndex()
        if 0 <= index < len(self._auto_purchase_values):
            return self._auto_purchase_values[index]
        return "none"

    def _sync_auto_purchase_fields(self) -> None:
        choice = self._current_auto_purchase_value()
        is_max = choice == "max_charges"
        is_none = choice == "none"

        self.auto_target_spin.setEnabled(is_max)
        self.auto_retain_spin.setEnabled(not is_none)

    def _get_current_editor_image_path(self) -> str | None:
        source = self.template_source_edit.text().strip()
        if source:
            source_path = Path(source)
            if source_path.is_file():
                return str(source_path)

        file_id = self.file_id_edit.text().strip()
        template_path = resolve_template_image(file_id)
        if template_path is None:
            return None
        return str(template_path)

    def _open_area_editor(self) -> None:
        try:
            selected_area = parse_selected_area(self.selected_area_edit.text())
        except Exception as exc:
            InfoBar.warning(
                title=tr("config.selected_area.title"),
                content=tr("config.selected_area.parse_failed", detail=str(exc)),
                **self.editor.infobar_options(duration=5000),
            )
            return

        image_path = self._get_current_editor_image_path()
        if image_path is None:
            InfoBar.warning(
                title=tr("config.selected_area.title"),
                content=tr("config.selected_area.no_template_image"),
                **self.editor.infobar_options(),
            )
            return

        dialog = AreaEditorDialog(self.editor, image_path=image_path, selected_area=selected_area)
        if dialog.exec() != int(dialog.DialogCode.Accepted):
            return

        self.selected_area_edit.setText(format_selected_area(dialog.result_area))
        if dialog.result_image_path:
            self.template_source_edit.setText(dialog.result_image_path)

    def load_user(self, user: dict[str, Any]) -> None:
        self.identifier_edit.setText(str(user.get("identifier") or ""))

        creds = user.get("credentials", {})
        self.token_edit.setText(str(creds.get("token") or ""))
        self.cf_clearance_edit.setText(str(creds.get("cf_clearance") or ""))

        template = user.get("template", {})
        self.file_id_edit.setText(str(template.get("file_id") or ""))
        self.coords_edit.setText(str(template.get("coords") or ""))
        self.template_source_edit.setText(str(user.get("_template_source") or ""))

        selected_area = user.get("selected_area")
        self.selected_area_edit.setText(
            format_selected_area(selected_area if isinstance(selected_area, tuple) else None)
        )

        self.preferred_colors_editor.set_colors(list(user.get("preferred_colors") or []))
        self.min_charges_spin.setValue(int(user.get("min_paint_charges") or 30))

        max_charges = user.get("max_paint_charges")
        has_max = isinstance(max_charges, int)
        self.max_enable_cb.setChecked(has_max)
        self.max_charges_spin.setEnabled(has_max)
        self.max_charges_spin.setValue(int(max_charges or 1))

        auto_purchase = user.get("auto_purchase")
        if not isinstance(auto_purchase, dict):
            self.auto_purchase_cb.setCurrentIndex(self._auto_purchase_index["none"])
            self.auto_target_spin.setValue(0)
            self.auto_retain_spin.setValue(0)
        else:
            choice = str(auto_purchase.get("type") or "none")
            self.auto_purchase_cb.setCurrentIndex(self._auto_purchase_index.get(choice, 0))
            self.auto_target_spin.setValue(int(auto_purchase.get("target_max") or 0))
            self.auto_retain_spin.setValue(int(auto_purchase.get("retain_droplets") or 0))

        self._sync_auto_purchase_fields()

    def save_to_user(self) -> dict[str, Any]:
        selected_area = parse_selected_area(self.selected_area_edit.text())
        self.selected_area_edit.setText(format_selected_area(selected_area))

        auto_choice = self._current_auto_purchase_value()
        auto_purchase: dict[str, Any] | None
        if auto_choice == "none":
            auto_purchase = None
        elif auto_choice == "max_charges":
            auto_purchase = {
                "type": "max_charges",
                "target_max": int(self.auto_target_spin.value()) or None,
                "retain_droplets": int(self.auto_retain_spin.value()),
            }
        else:
            auto_purchase = {
                "type": "charges",
                "retain_droplets": int(self.auto_retain_spin.value()),
            }

        return {
            "identifier": self.identifier_edit.text().strip(),
            "credentials": {
                "token": self.token_edit.toPlainText().strip(),
                "cf_clearance": self.cf_clearance_edit.toPlainText().strip(),
            },
            "template": {
                "file_id": self.file_id_edit.text().strip(),
                "coords": self.coords_edit.text().strip(),
            },
            "selected_area": selected_area,
            "preferred_colors": self.preferred_colors_editor.colors(),
            "auto_purchase": auto_purchase,
            "min_paint_charges": int(self.min_charges_spin.value()),
            "max_paint_charges": int(self.max_charges_spin.value()) if self.max_enable_cb.isChecked() else None,
            "_template_source": self.template_source_edit.text().strip(),
        }
