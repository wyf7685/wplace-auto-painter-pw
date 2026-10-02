import json
import os
from collections.abc import Iterator
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPointF, Qt
from PySide6.QtGui import QEnterEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget
from qfluentwidgets import TeachingTip

import app.gui.config.editor as editor_module
from app.const import assets
from app.gui.config.area_editor_dialog import AreaEditorDialog
from app.gui.config.editor import ConfigEditorWidget
from app.gui.config.help_hint import HOVER_OPEN_DELAY_MS, HelpHintButton, _HelpTipView
from app.i18n import tr

CONFIG_HELP_KEYS = frozenset(
    {
        "config.help.proxy",
        "config.help.cf_clearance",
        "config.help.template_file_id",
        "config.help.template_coords",
        "config.help.template_source",
        "config.help.selected_area",
        "config.help.preferred_colors",
        "config.help.paint_input_mode",
        "config.help.min_paint_charges",
        "config.help.max_paint_charges",
        "config.help.auto_purchase",
        "config.help.auto_target_max",
        "config.help.auto_retain_droplets",
    }
)
AREA_HELP_KEYS = frozenset(
    {
        "area_editor.help.use_current_selection",
        "area_editor.help.clear_selection",
    }
)


@pytest.fixture
def qapp() -> Iterator[QApplication]:
    app_instance = QApplication.instance()
    app = app_instance if isinstance(app_instance, QApplication) else QApplication([])
    yield app
    HelpHintButton.close_tip()
    app.processEvents()


def _enter(button: HelpHintButton) -> None:
    button.enterEvent(QEnterEvent(QPointF(1, 1), QPointF(1, 1), QPointF(1, 1)))


def _leave(button: HelpHintButton) -> None:
    button.leaveEvent(QEvent(QEvent.Type.Leave))


def _wait_for_hover() -> None:
    QTest.qWait(HOVER_OPEN_DELAY_MS + 50)


def _visible_tips(root: QWidget) -> list[TeachingTip]:
    return [tip for tip in root.findChildren(TeachingTip) if tip.isVisible()]


def _cleanup(root: QWidget) -> None:
    HelpHintButton.close_tip()
    root.close()
    root.deleteLater()
    app = QApplication.instance()
    if isinstance(app, QApplication):
        app.processEvents()


def test_help_hint_opens_on_hover_and_closes_on_click(qapp: QApplication) -> None:
    host = QWidget()
    button = HelpHintButton("config.help.selected_area", host)
    layout = QHBoxLayout(host)
    layout.addWidget(button)
    host.resize(320, 160)
    host.show()
    qapp.processEvents()
    try:
        _enter(button)
        _wait_for_hover()
        tips = _visible_tips(host)
        assert len(tips) == 1
        text = tips[0].view.contentLabel.text()
        assert text == tr("config.help.selected_area")
        assert "\n" in text
        assert "。" not in text
        label = tips[0].view.contentLabel
        assert label.wordWrap() is False
        longest = max(label.fontMetrics().horizontalAdvance(line) for line in text.splitlines())
        assert label.minimumWidth() >= longest
        assert label.height() <= label.fontMetrics().lineSpacing() * len(text.splitlines()) + 4

        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        qapp.processEvents()
        assert _visible_tips(host) == []

        _enter(button)
        _wait_for_hover()
        assert _visible_tips(host) == []

        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        qapp.processEvents()
        assert _visible_tips(host) == []

        _leave(button)
        _enter(button)
        _wait_for_hover()
        reopened = _visible_tips(host)
        assert len(reopened) == 1
        assert reopened[0].view.contentLabel.text() == tr("config.help.selected_area")
    finally:
        _cleanup(host)


def test_help_tip_keeps_each_sentence_on_one_line(qapp: QApplication) -> None:
    sentence = "W" * 180
    view = _HelpTipView(f"{sentence}\nshort")
    label = view.contentLabel
    advance = label.fontMetrics().horizontalAdvance(sentence)
    assert advance > 700
    assert label.wordWrap() is False
    assert label.minimumWidth() >= advance
    assert label.maximumWidth() >= advance
    view.show()
    qapp.processEvents()
    assert label.height() <= label.fontMetrics().lineSpacing() * 2 + 4
    view.close()
    view.deleteLater()
    qapp.processEvents()


def test_help_hint_switches_and_closes_for_outside_press_or_scroll(qapp: QApplication) -> None:
    host = QWidget()
    scroll = QScrollArea(host)
    content = QWidget()
    content_layout = QVBoxLayout(content)
    first = HelpHintButton("config.help.proxy", content)
    second = HelpHintButton("config.help.selected_area", content)
    outside = QWidget(content)
    outside.setFixedSize(40, 40)
    content_layout.addWidget(first)
    content_layout.addWidget(second)
    content_layout.addWidget(outside)
    content_layout.addSpacing(600)
    scroll.setWidget(content)
    scroll.setWidgetResizable(True)
    layout = QVBoxLayout(host)
    layout.addWidget(scroll)
    host.resize(360, 180)
    host.show()
    qapp.processEvents()
    try:
        _enter(first)
        _wait_for_hover()
        assert len(_visible_tips(host)) == 1
        assert HelpHintButton._owner is first

        _leave(first)
        _enter(second)
        _wait_for_hover()
        visible = _visible_tips(host)
        assert len(visible) == 1
        assert HelpHintButton._owner is second
        assert visible[0].view.contentLabel.text() == tr("config.help.selected_area")

        QTest.mouseClick(outside, Qt.MouseButton.LeftButton)
        qapp.processEvents()
        assert _visible_tips(host) == []

        _leave(second)
        _enter(second)
        _wait_for_hover()
        assert len(_visible_tips(host)) == 1
        bar = scroll.verticalScrollBar()
        assert bar is not None
        assert bar.maximum() > 0
        bar.setValue(bar.maximum())
        qapp.processEvents()
        assert _visible_tips(host) == []
    finally:
        _cleanup(host)


def test_config_editor_and_area_editor_place_help_buttons(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(editor_module, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(editor_module, "TEMPLATES_DIR", tmp_path / "templates")
    editor = ConfigEditorWidget()
    editor.show()
    qapp.processEvents()
    dialog: AreaEditorDialog | None = None
    try:
        config_keys = {button.help_key for button in editor.findChildren(HelpHintButton)}
        assert config_keys == CONFIG_HELP_KEYS
        dialog = AreaEditorDialog(editor, image_path=None, selected_area=None)
        dialog.show()
        qapp.processEvents()
        area_keys = {button.help_key for button in dialog.findChildren(HelpHintButton)}
        assert area_keys == AREA_HELP_KEYS
    finally:
        if dialog is not None:
            dialog.close()
            dialog.deleteLater()
        _cleanup(editor)


def test_paint_input_mode_help_names_each_option() -> None:
    zh = json.loads((assets.locales / "zh_CN.json").read_text(encoding="utf-8"))
    en = json.loads((assets.locales / "en_US.json").read_text(encoding="utf-8"))
    for locale in (zh, en):
        help_text = locale["config.help.paint_input_mode"]
        for key in (
            "config.paint_input_mode.click",
            "config.paint_input_mode.space_drag",
            "config.paint_input_mode.space_drag_retrace",
        ):
            assert locale[key] in help_text


def test_help_strings_exist_in_both_locales() -> None:
    zh = json.loads((assets.locales / "zh_CN.json").read_text(encoding="utf-8"))
    en = json.loads((assets.locales / "en_US.json").read_text(encoding="utf-8"))
    prefixes = ("config.help.", "area_editor.help.")
    zh_keys = {key for key in zh if key.startswith(prefixes)}
    en_keys = {key for key in en if key.startswith(prefixes)}
    assert zh_keys == en_keys
    assert CONFIG_HELP_KEYS | AREA_HELP_KEYS | {"config.help.button"} <= zh_keys
    for key in zh_keys:
        assert isinstance(zh[key], str)
        assert isinstance(en[key], str)
        assert zh[key].strip()
        assert en[key].strip()
        assert zh[key] != en[key]
        if key == "config.help.button":
            continue
        assert "。" not in zh[key]
        assert "\n" in zh[key]
        assert ". " not in en[key]
        assert not en[key].endswith(".")
