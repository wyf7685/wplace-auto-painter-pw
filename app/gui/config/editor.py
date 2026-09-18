import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from pydantic import ValidationError
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QSplitter, QVBoxLayout, QWidget
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
    StrongBodyLabel,
    SubtitleLabel,
)

from app.config import Config, export_config_schema
from app.const import CONFIG_FILE, TEMPLATES_DIR
from app.i18n import lang, tr
from app.schemas import WplacePixelCoords

from .constants import BROWSER_TYPES, LANGUAGE_CODES, LOG_LEVELS
from .user_detail_card import UserDetailCard
from .user_draft import default_user, normalize_user

ConfigField = Literal["identifier", "token", "template_file_id", "template_coords", "template_source"]


@dataclass(frozen=True, slots=True)
class ConfigSaveResult:
    error: str | None = None
    user_index: int | None = None
    field: ConfigField | None = None

    @property
    def success(self) -> bool:
        return self.error is None


class _ConfigFieldError(ValueError):
    def __init__(self, message: str, *, user_index: int, field: ConfigField) -> None:
        super().__init__(message)
        self.user_index = user_index
        self.field = field


class ConfigEditorWidget(QWidget):
    """Fluent configuration editor with modular widgets and pydantic validation."""

    def __init__(self) -> None:
        super().__init__()
        self._users: list[dict[str, Any]] = []
        self._current_user_row = -1

        self._build_widgets()
        self._build_layout()
        self.load_from_disk()

    def _build_widgets(self) -> None:
        self.title_label = SubtitleLabel(tr("config.title"))

        self.browser_cb = ComboBox()
        self.browser_cb.addItems(BROWSER_TYPES)

        self.log_level_cb = ComboBox()
        self.log_level_cb.addItems(LOG_LEVELS)

        self.language_cb = ComboBox()
        self._language_codes = LANGUAGE_CODES
        self._language_index = {code: index for index, code in enumerate(self._language_codes)}
        self.language_cb.addItems([tr(f"language.{code.lower()}") for code in self._language_codes])

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

        self.user_detail_card = UserDetailCard(self)

    def _build_layout(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)
        root.addWidget(self.title_label)

        root.addWidget(self._build_global_card())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(2)
        splitter.addWidget(self._build_users_list_card())
        splitter.addWidget(self.user_detail_card)
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

    def infobar_options(self, *, duration: int = 3000) -> dict[str, Any]:
        return {
            "orient": Qt.Orientation.Horizontal,
            "isClosable": True,
            "position": InfoBarPosition.TOP_RIGHT,
            "duration": duration,
            "parent": self,
        }

    def focus_save_error(self, result: ConfigSaveResult) -> None:
        if result.user_index is None or result.field is None:
            return

        self.users_list.setCurrentRow(result.user_index)
        field_widgets: dict[ConfigField, QWidget] = {
            "identifier": self.user_detail_card.identifier_edit,
            "token": self.user_detail_card.token_edit,
            "template_file_id": self.user_detail_card.file_id_edit,
            "template_coords": self.user_detail_card.coords_edit,
            "template_source": self.user_detail_card.template_source_edit,
        }
        QTimer.singleShot(0, field_widgets[result.field].setFocus)

    def _current_language_code(self) -> str:
        index = self.language_cb.currentIndex()
        if 0 <= index < len(self._language_codes):
            return self._language_codes[index]
        return "zh_CN"

    def load_from_disk(self) -> None:
        raw: dict[str, Any] = {}
        if CONFIG_FILE.is_file():
            try:
                raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
            except Exception as exc:
                InfoBar.warning(
                    title=tr("config.title"),
                    content=tr("config.load.parse_failed", detail=str(exc)),
                    **self.infobar_options(),
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
                    **self.infobar_options(),
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
        self.user_detail_card.user_loaded.emit(user)

    def _store_current_user(self) -> None:
        row = self._current_user_row
        if row < 0 or row >= len(self._users):
            return

        user = self.user_detail_card.save_to_user()
        if not user.get("identifier"):
            user["identifier"] = self._users[row].get("identifier", f"user-{row + 1}")

        self._users[row] = user

        if (item := self.users_list.item(row)) is not None:
            item.setText(user["identifier"])

    def _add_user(self) -> None:
        if self._current_user_row >= 0:
            try:
                self._store_current_user()
            except Exception as exc:
                InfoBar.warning(
                    title=tr("config.title"),
                    content=tr("config.user.add_failed", detail=str(exc)),
                    **self.infobar_options(duration=-1),
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
                **self.infobar_options(),
            )
            return

        # Mutating the list emits currentRowChanged, which would make _on_user_changed
        # flush the detail card (still holding the removed user) into a now-shifted row.
        self.users_list.blockSignals(True)
        del self._users[row]
        self.users_list.takeItem(row)
        target = min(row, len(self._users) - 1)
        self.users_list.setCurrentRow(target)
        self.users_list.blockSignals(False)

        self._current_user_row = -1
        self._on_user_changed(target)

    def save_to_disk(self, show_message: bool = True) -> ConfigSaveResult:
        selected_language = self._current_language_code()
        try:
            self._store_current_user()

            users_payload: list[dict[str, Any]] = []
            for user_index, user in enumerate(self._users):
                identifier = str(user["identifier"] or "").strip()
                token = str(user["credentials"]["token"] or "").strip()
                file_id = str(user["template"]["file_id"] or "").strip()
                coords_text = str(user["template"]["coords"] or "").strip()
                source = str(user.get("_template_source") or "").strip()

                if not identifier:
                    raise _ConfigFieldError(
                        tr("config.validation.identifier_empty"),
                        user_index=user_index,
                        field="identifier",
                    )
                if not token:
                    raise _ConfigFieldError(
                        tr("config.validation.token_empty", identifier=identifier),
                        user_index=user_index,
                        field="token",
                    )
                if not file_id:
                    raise _ConfigFieldError(
                        tr("config.validation.template_file_id_empty", identifier=identifier),
                        user_index=user_index,
                        field="template_file_id",
                    )
                if not coords_text:
                    raise _ConfigFieldError(
                        tr("config.validation.template_coords_empty", identifier=identifier),
                        user_index=user_index,
                        field="template_coords",
                    )

                try:
                    coords = WplacePixelCoords.parse(coords_text)
                except ValueError as exc:
                    raise _ConfigFieldError(
                        str(exc),
                        user_index=user_index,
                        field="template_coords",
                    ) from exc

                user_payload = {
                    "identifier": identifier,
                    "credentials": {
                        "token": token,
                        "cf_clearance": user["credentials"]["cf_clearance"] or None,
                    },
                    "template": {
                        "file_id": file_id,
                        "coords": {
                            "tlx": coords.tlx,
                            "tly": coords.tly,
                            "pxx": coords.pxx,
                            "pxy": coords.pxy,
                        },
                    },
                    "selected_area": user["selected_area"],
                    "preferred_colors": user["preferred_colors"],
                    "paint_input_mode": user["paint_input_mode"],
                    "auto_purchase": user["auto_purchase"],
                    "min_paint_charges": user["min_paint_charges"],
                    "max_paint_charges": user["max_paint_charges"],
                }

                if source:
                    src = Path(source)
                    if not src.is_file():
                        raise _ConfigFieldError(
                            tr("config.validation.template_source_missing", path=source),
                            user_index=user_index,
                            field="template_source",
                        )
                    dest = TEMPLATES_DIR / f"{file_id}.png"
                    TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
                    if src.resolve() != dest.resolve():
                        shutil.copy2(src, dest)
                else:
                    dest = TEMPLATES_DIR / f"{file_id}.png"
                    if not dest.is_file() or dest.stat().st_size == 0:
                        raise _ConfigFieldError(
                            tr("config.validation.template_image_missing", path=dest),
                            user_index=user_index,
                            field="template_source",
                        )

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

        except _ConfigFieldError as exc:
            result = ConfigSaveResult(error=str(exc), user_index=exc.user_index, field=exc.field)
            if show_message:
                InfoBar.error(
                    title=tr("config.save.validation_error.title"),
                    content=result.error or tr("controller.invalid_config.content"),
                    **self.infobar_options(duration=-1),
                )
                self.focus_save_error(result)
            return result
        except ValidationError as exc:
            result = ConfigSaveResult(error=str(exc))
            if show_message:
                InfoBar.error(
                    title=tr("config.save.validation_error.title"),
                    content=result.error,
                    **self.infobar_options(duration=-1),
                )
            return result
        except Exception as exc:
            result = ConfigSaveResult(error=str(exc))
            if show_message:
                InfoBar.error(
                    title=tr("config.save.failed.title"),
                    content=result.error,
                    **self.infobar_options(duration=-1),
                )
            return result
        else:
            if show_message:
                InfoBar.success(
                    title=tr("config.save.success.title"),
                    content=tr("config.save.success.content", path=CONFIG_FILE),
                    **self.infobar_options(),
                )
                if selected_language != lang.get_language():
                    InfoBar.info(
                        title=tr("config.language.change_pending.title"),
                        content=tr("config.language.change_pending.content"),
                        **self.infobar_options(),
                    )
            return ConfigSaveResult()
