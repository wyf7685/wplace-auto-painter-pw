import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QFileDialog, QVBoxLayout, QWidget

import app.gui.config.editor as editor_module
import app.gui.controller as controller_module
from app.gui.config.editor import ConfigEditorWidget
from app.gui.controller import Controller
from app.i18n import tr


@pytest.fixture
def config_editor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> Iterator[tuple[QApplication, ConfigEditorWidget]]:
    monkeypatch.setattr(editor_module, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(editor_module, "TEMPLATES_DIR", tmp_path / "templates")

    app_instance = QApplication.instance()
    app = app_instance if isinstance(app_instance, QApplication) else QApplication([])
    editor = ConfigEditorWidget()
    editor.show()
    app.processEvents()
    try:
        yield app, editor
    finally:
        editor.close()
        editor.deleteLater()
        app.processEvents()


def test_browse_template_source_fills_only_empty_file_id(
    config_editor: tuple[QApplication, ConfigEditorWidget],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, editor = config_editor
    card = editor.user_detail_card
    selected_path = tmp_path / "neuroFACE.png"
    selected_path.write_bytes(b"template")

    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(selected_path), ""),
    )

    card.file_id_edit.clear()
    card.template_source_btn.click()
    assert card.template_source_edit.text() == str(selected_path)
    assert card.file_id_edit.text() == "neuroFACE"

    card.file_id_edit.setText("custom-template")
    card.template_source_btn.click()
    assert card.file_id_edit.text() == "custom-template"


def test_save_derives_file_id_from_manually_entered_source(
    config_editor: tuple[QApplication, ConfigEditorWidget],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, editor = config_editor
    card = editor.user_detail_card
    selected_path = tmp_path / "neuroFACE.png"
    selected_path.write_bytes(b"template")

    card.identifier_edit.setText("issue-12-user")
    card.token_edit.setPlainText("redacted-token")
    card.file_id_edit.clear()
    card.template_source_edit.setText(str(selected_path))

    monkeypatch.setattr(editor_module, "export_config_schema", lambda: None)
    monkeypatch.setattr(editor_module.Config, "save", lambda _self: None)

    result = editor.save_to_disk(show_message=False)

    assert result.success
    assert card.file_id_edit.text() == "neuroFACE"
    assert (tmp_path / "templates" / "neuroFACE.png").read_bytes() == b"template"
    assert card.template_source_edit.text() == ""

    selected_path.unlink()
    assert editor.save_to_disk(show_message=False).success


def test_save_validation_error_remains_until_closed(
    config_editor: tuple[QApplication, ConfigEditorWidget],
) -> None:
    app, editor = config_editor
    card = editor.user_detail_card
    card.identifier_edit.setText("issue-12-user")
    card.token_edit.setPlainText("redacted-token")
    card.file_id_edit.clear()
    card.template_source_edit.clear()

    result = editor.save_to_disk(show_message=True)
    app.processEvents()

    expected_error = tr("config.validation.template_file_id_empty", identifier="issue-12-user")
    info_bars = editor.findChildren(editor_module.InfoBar)
    assert not result.success
    assert len(info_bars) == 1
    assert info_bars[0].contentLabel.text() == expected_error
    assert info_bars[0].duration < 0


def test_start_shows_persistent_file_id_error_and_focuses_field(
    config_editor: tuple[QApplication, ConfigEditorWidget],
) -> None:
    app, editor = config_editor
    card = editor.user_detail_card
    card.identifier_edit.setText("issue-12-user")
    card.token_edit.setPlainText("redacted-token")
    card.file_id_edit.clear()
    card.template_source_edit.clear()

    class WindowStub(QWidget):
        def __init__(self) -> None:
            super().__init__()
            self.config_editor = editor
            self.config_page_selected = False
            layout = QVBoxLayout(self)
            layout.addWidget(editor)

        def goto_config_page(self) -> None:
            self.config_page_selected = True

        def goto_logs_page(self) -> None:
            raise AssertionError("Logs page must not open when configuration is invalid")

    class RuntimeStub:
        def start(self) -> bool:
            raise AssertionError("Runtime must not start when configuration is invalid")

    window = WindowStub()
    window.show()
    controller: Any = object.__new__(Controller)
    controller.window = window
    controller.runtime = RuntimeStub()

    try:
        Controller.start_runtime(controller)
        app.processEvents()

        expected_error = tr("config.validation.template_file_id_empty", identifier="issue-12-user")
        info_bars = window.findChildren(controller_module.InfoBar)
        assert len(info_bars) == 1
        assert info_bars[0].contentLabel.text() == expected_error
        assert info_bars[0].duration < 0
        assert window.config_page_selected
        assert QApplication.focusWidget() is card.file_id_edit
    finally:
        editor.setParent(None)
        window.close()
        window.deleteLater()
        app.processEvents()


def test_selected_area_validation_targets_field(
    config_editor: tuple[QApplication, ConfigEditorWidget],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _, editor = config_editor
    card = editor.user_detail_card
    selected_path = tmp_path / "template.png"
    selected_path.write_bytes(b"template")

    card.identifier_edit.setText("area-user")
    card.token_edit.setPlainText("redacted-token")
    card.file_id_edit.setText("area-template")
    card.coords_edit.setText("1,2,3,4")
    card.template_source_edit.setText(str(selected_path))
    card.selected_area_edit.setText("-1,0,4,5")

    monkeypatch.setattr(editor_module, "export_config_schema", lambda: None)
    monkeypatch.setattr(editor_module.Config, "save", lambda _self: None)

    result = editor.save_to_disk(show_message=False)

    assert not result.success
    assert result.user_index == 0
    assert result.field == "selected_area"
    assert result.error == tr("config.validation.selected_area_origin", identifier="area-user")


def test_editor_tracks_unsaved_widget_changes(
    config_editor: tuple[QApplication, ConfigEditorWidget],
) -> None:
    _, editor = config_editor

    assert not editor.has_unsaved_changes()
    editor.user_detail_card.identifier_edit.setText("changed-user")
    assert editor.has_unsaved_changes()
