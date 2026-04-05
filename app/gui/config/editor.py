import json
import shutil
from pathlib import Path
from typing import Any

from pydantic import ValidationError
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QSplitter,
    QVBoxLayout,
    QWidget,
)
from qfluentwidgets import (
    BodyLabel,
    CheckBox,
    ComboBox,
    ElevatedCardWidget,
    InfoBar,
    InfoBarPosition,
    LineEdit,
    ListWidget,
    PrimaryPushButton,
    PushButton,
    SmoothScrollArea,
    SpinBox,
    StrongBodyLabel,
    SubtitleLabel,
    TextEdit,
)

from app.config import Config, export_config_schema
from app.const import CONFIG_FILE, TEMPLATES_DIR
from app.gui.i18n import lang, tr
from app.schemas import WplacePixelCoords

from .area_editor_dialog import AreaEditorDialog
from .constants import BROWSER_TYPES, LOG_LEVELS
from .preferred_colors import PreferredColorsEditor
from .user_draft import (
    default_user,
    format_selected_area,
    normalize_user,
    parse_selected_area,
    resolve_template_image,
)


class ConfigEditorWidget(QWidget):
    """Fluent configuration editor with modular widgets and pydantic validation."""

    saved = Signal()

    def __init__(self) -> None:
        super().__init__()
        self._users: list[dict[str, Any]] = []
        self._current_user_row = -1

        self._build_widgets()
        self._build_layout()
        self.load_from_disk()

    def _build_widgets(self) -> None:
        self.title_label = SubtitleLabel(tr("config.title"))
        # self.subtitle_label = BodyLabel("Manage runtime, users and template settings")

        self.browser_cb = ComboBox()
        self.browser_cb.addItems(BROWSER_TYPES)

        self.log_level_cb = ComboBox()
        self.log_level_cb.addItems(LOG_LEVELS)

        self.language_cb = ComboBox()
        self._language_codes = ["zh_CN", "en_US"]
        self._language_index = {code: index for index, code in enumerate(self._language_codes)}
        self.language_cb.addItems([tr("language.zh_cn"), tr("language.en_us")])

        self.proxy_edit = LineEdit()
        self.proxy_edit.setPlaceholderText(tr("config.placeholder.proxy"))

        self.check_update_cb = CheckBox(tr("config.flag.check_update"))
        self.disable_notifications_cb = CheckBox(tr("config.flag.disable_notifications"))

        self.users_list = ListWidget()
        self.users_list.currentRowChanged.connect(self._on_user_changed)

        self.add_user_btn = PrimaryPushButton(tr("config.user.add"))
        self.add_user_btn.clicked.connect(self._add_user)

        self.remove_user_btn = PushButton(tr("config.user.remove"))
        self.remove_user_btn.clicked.connect(self._remove_user)

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

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        root.addWidget(self.title_label)
        # root.addWidget(self.subtitle_label)

        root.addWidget(self._build_global_card())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(2)
        splitter.addWidget(self._build_users_list_card())
        splitter.addWidget(self._build_user_detail_card())
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 5)

        root.addWidget(splitter, stretch=1)

    def _build_global_card(self) -> QWidget:
        card = ElevatedCardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        layout.addWidget(StrongBodyLabel(tr("config.global.title")))

        top_row = QHBoxLayout()
        top_row.setSpacing(12)

        browser_col = QVBoxLayout()
        browser_col.setSpacing(4)
        browser_col.addWidget(BodyLabel(tr("config.global.browser")))
        browser_col.addWidget(self.browser_cb)

        log_level_col = QVBoxLayout()
        log_level_col.setSpacing(4)
        log_level_col.addWidget(BodyLabel(tr("config.global.log_level")))
        log_level_col.addWidget(self.log_level_cb)

        language_col = QVBoxLayout()
        language_col.setSpacing(4)
        language_col.addWidget(BodyLabel(tr("config.global.language")))
        language_col.addWidget(self.language_cb)

        proxy_col = QVBoxLayout()
        proxy_col.setSpacing(4)
        proxy_col.addWidget(BodyLabel(tr("config.global.proxy")))
        proxy_col.addWidget(self.proxy_edit)

        top_row.addLayout(browser_col, 2)
        top_row.addLayout(log_level_col, 2)
        top_row.addLayout(language_col, 2)
        top_row.addLayout(proxy_col, 4)
        layout.addLayout(top_row)

        flags_row = QHBoxLayout()
        flags_row.setSpacing(10)
        flags_row.addWidget(self.check_update_cb)
        flags_row.addWidget(self.disable_notifications_cb)
        flags_row.addStretch()
        layout.addLayout(flags_row)
        return card

    def _build_users_list_card(self) -> QWidget:
        card = ElevatedCardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)

        layout.addWidget(StrongBodyLabel(tr("config.users.title")))
        layout.addWidget(self.users_list, stretch=1)

        actions = QHBoxLayout()
        actions.addWidget(self.add_user_btn)
        actions.addWidget(self.remove_user_btn)
        layout.addLayout(actions)

        return card

    def _build_user_detail_card(self) -> QWidget:
        card = ElevatedCardWidget(self)
        layout = QVBoxLayout(card)
        layout.setContentsMargins(14, 12, 14, 12)
        layout.setSpacing(10)

        layout.addWidget(StrongBodyLabel(tr("config.user_profile.title")))

        form_host = QWidget(card)
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

        scroll = SmoothScrollArea(card)
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
        return card

    def _infobar_options(self, *, duration: int = 3000) -> dict[str, Any]:
        return {
            "orient": Qt.Orientation.Horizontal,
            "isClosable": True,
            "position": InfoBarPosition.TOP_RIGHT,
            "duration": duration,
            "parent": self,
        }

    def _current_language_code(self) -> str:
        index = self.language_cb.currentIndex()
        if 0 <= index < len(self._language_codes):
            return self._language_codes[index]
        return "zh_CN"

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
                **self._infobar_options(duration=5000),
            )
            return

        image_path = self._get_current_editor_image_path()
        if image_path is None:
            InfoBar.warning(
                title=tr("config.selected_area.title"),
                content=tr("config.selected_area.no_template_image"),
                **self._infobar_options(),
            )
            return

        dialog = AreaEditorDialog(self, image_path=image_path, selected_area=selected_area)
        if dialog.exec() != int(dialog.DialogCode.Accepted):
            return

        self.selected_area_edit.setText(format_selected_area(dialog.result_area))
        if dialog.result_image_path:
            self.template_source_edit.setText(dialog.result_image_path)

    def load_from_disk(self) -> None:
        raw: dict[str, Any] = {}
        if CONFIG_FILE.is_file():
            try:
                raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except Exception as exc:
                InfoBar.warning(
                    title=tr("config.title"),
                    content=tr("config.load.parse_failed", detail=str(exc)),
                    **self._infobar_options(),
                )

        language = str(raw.get("language") or "zh_CN")
        self.language_cb.setCurrentIndex(self._language_index.get(language, 0))

        self.browser_cb.setCurrentText(str(raw.get("browser") or "chromium"))
        self.log_level_cb.setCurrentText(str(raw.get("log_level") or "DEBUG"))
        self.proxy_edit.setText(str(raw.get("proxy") or ""))
        self.check_update_cb.setChecked(bool(raw.get("check_update", True)))
        self.check_update_cb.setToolTip(tr("config.flag.check_update.tooltip"))
        self.disable_notifications_cb.setChecked(bool(raw.get("disable_notifications", False)))
        self.disable_notifications_cb.setToolTip(tr("config.flag.disable_notifications.tooltip"))

        users = raw.get("users")
        if not isinstance(users, list):
            users = []
        self._users = [normalize_user(u) for u in users if isinstance(u, dict)]

        if not self._users:
            self._users = [default_user("user-1")]

        self.users_list.clear()
        for user in self._users:
            self.users_list.addItem(str(user["identifier"]))

        self.users_list.setCurrentRow(0)

    def _on_user_changed(self, row: int) -> None:
        if self._current_user_row >= 0:
            try:
                self._store_current_user()
            except Exception as exc:
                InfoBar.warning(
                    title=tr("config.title"),
                    content=tr("config.user.switch_failed", detail=str(exc)),
                    **self._infobar_options(),
                )
                self.users_list.blockSignals(True)
                self.users_list.setCurrentRow(self._current_user_row)
                self.users_list.blockSignals(False)
                return

        if row < 0 or row >= len(self._users):
            self._current_user_row = -1
            return

        self._current_user_row = row
        self._load_user(row)

    def _load_user(self, row: int) -> None:
        user = self._users[row]
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

    def _store_current_user(self) -> None:
        row = self._current_user_row
        if row < 0 or row >= len(self._users):
            return

        identifier = self.identifier_edit.text().strip()
        if not identifier:
            identifier = f"user-{row + 1}"

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

        max_paint_charges: int | None = int(self.max_charges_spin.value()) if self.max_enable_cb.isChecked() else None

        self._users[row] = {
            "identifier": identifier,
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
            "max_paint_charges": max_paint_charges,
            "_template_source": self.template_source_edit.text().strip(),
        }

        item = self.users_list.item(row)
        item.setText(identifier)

    def _add_user(self) -> None:
        if self._current_user_row >= 0:
            try:
                self._store_current_user()
            except Exception as exc:
                InfoBar.warning(
                    title=tr("config.title"),
                    content=tr("config.user.add_failed", detail=str(exc)),
                    **self._infobar_options(duration=0),
                )
                return

        base = "user"
        idx = 1
        existing = {str(u.get("identifier")) for u in self._users}
        while f"{base}-{idx}" in existing:
            idx += 1

        user = default_user(f"{base}-{idx}")
        self._users.append(user)
        self.users_list.addItem(str(user["identifier"]))
        self.users_list.setCurrentRow(self.users_list.count() - 1)

    def _remove_user(self) -> None:
        row = self.users_list.currentRow()
        if row < 0 or row >= len(self._users):
            return

        if len(self._users) == 1:
            InfoBar.warning(
                title=tr("config.title"),
                content=tr("config.user.at_least_one"),
                **self._infobar_options(),
            )
            return

        del self._users[row]
        self.users_list.takeItem(row)

        target = min(row, len(self._users) - 1)
        self.users_list.setCurrentRow(target)

    def _pick_template_source(self) -> None:
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            tr("config.template_dialog.title"),
            "",
            tr("config.template_dialog.filter"),
        )
        if file_path:
            self.template_source_edit.setText(file_path)

    def save_to_disk(self, show_message: bool = True) -> bool:
        selected_language = self._current_language_code()
        try:
            self._store_current_user()

            users_payload: list[dict[str, Any]] = []
            for user in self._users:
                coords = WplacePixelCoords.parse(str(user["template"]["coords"]))
                user_payload = {
                    "identifier": user["identifier"],
                    "credentials": {
                        "token": user["credentials"]["token"],
                        "cf_clearance": user["credentials"]["cf_clearance"] or None,
                    },
                    "template": {
                        "file_id": user["template"]["file_id"],
                        "coords": {
                            "tlx": coords.tlx,
                            "tly": coords.tly,
                            "pxx": coords.pxx,
                            "pxy": coords.pxy,
                        },
                    },
                    "selected_area": user["selected_area"],
                    "preferred_colors": user["preferred_colors"],
                    "auto_purchase": user["auto_purchase"],
                    "min_paint_charges": user["min_paint_charges"],
                    "max_paint_charges": user["max_paint_charges"],
                }

                if not str(user_payload["identifier"]).strip():
                    raise ValueError(tr("config.validation.identifier_empty"))
                if not str(user_payload["credentials"]["token"] or "").strip():
                    raise ValueError(tr("config.validation.token_empty", identifier=user_payload["identifier"]))
                if not str(user_payload["template"]["file_id"] or "").strip():
                    raise ValueError(
                        tr("config.validation.template_file_id_empty", identifier=user_payload["identifier"])
                    )
                if not str(user_payload["template"]["coords"] or "").strip():
                    raise ValueError(
                        tr("config.validation.template_coords_empty", identifier=user_payload["identifier"])
                    )

                source = str(user.get("_template_source") or "").strip()
                if source:
                    src = Path(source)
                    if not src.is_file():
                        raise ValueError(tr("config.validation.template_source_missing", path=source))
                    dest = TEMPLATES_DIR / f"{user_payload['template']['file_id']}.png"
                    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
                    if src.resolve() != dest.resolve():
                        shutil.copy2(src, dest)
                else:
                    dest = TEMPLATES_DIR / f"{user_payload['template']['file_id']}.png"
                    if not dest.is_file() or dest.stat().st_size == 0:
                        raise ValueError(tr("config.validation.template_image_missing", path=dest))

                users_payload.append(user_payload)

            payload: dict[str, Any] = {
                "users": users_payload,
                "browser": self.browser_cb.currentText(),
                "proxy": self.proxy_edit.text().strip() or None,
                "log_level": self.log_level_cb.currentText(),
                "check_update": self.check_update_cb.isChecked(),
                "disable_notifications": self.disable_notifications_cb.isChecked(),
                "language": selected_language,
            }

            config = Config.model_validate(payload)
            export_config_schema()
            config.save()
            self.saved.emit()

        except ValidationError as exc:
            if show_message:
                InfoBar.error(
                    title=tr("config.save.validation_error.title"),
                    content=str(exc),
                    **self._infobar_options(duration=0),
                )
            return False
        except Exception as exc:
            if show_message:
                InfoBar.error(
                    title=tr("config.save.failed.title"),
                    content=str(exc),
                    **self._infobar_options(duration=0),
                )
            return False
        else:
            if show_message:
                InfoBar.success(
                    title=tr("config.save.success.title"),
                    content=tr("config.save.success.content", path=CONFIG_FILE),
                    **self._infobar_options(),
                )
                if selected_language != lang.get_language():
                    InfoBar.info(
                        title=tr("config.language.change_pending.title"),
                        content=tr("config.language.change_pending.content"),
                        **self._infobar_options(),
                    )
            return True
