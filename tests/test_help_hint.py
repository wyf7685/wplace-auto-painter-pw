import os
from collections.abc import Iterator
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QEvent, QPoint, QPointF, QRect, Qt
from PySide6.QtGui import QEnterEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget
from qfluentwidgets import TeachingTip

import app.gui.config.editor as editor_module
from app.gui.config.editor import ConfigEditorWidget
from app.gui.config.help_hint import HOVER_OPEN_DELAY_MS, HelpHintButton, _HelpTipView


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


def _assert_button_input_clear(app: QApplication, button: HelpHintButton) -> None:
    for tip in _visible_tips(button.window()):
        target_rect = QRect(tip.mapFromGlobal(button.mapToGlobal(QPoint())), button.size())
        overlap = tip.rect().intersected(target_rect)
        if not overlap.isEmpty():
            assert not tip.mask().isEmpty()
            assert not tip.mask().intersects(overlap)
    # The offscreen plugin ignores native window masks; native smoke verifies actual hit testing.
    if app.platformName() != "offscreen":
        for point in (button.rect().topLeft(), button.rect().center(), button.rect().bottomRight()):
            assert app.widgetAt(button.mapToGlobal(point)) is button


def _click_button_at_position(app: QApplication, button: HelpHintButton) -> None:
    _assert_button_input_clear(app, button)
    position = button.mapToGlobal(button.rect().center())
    target = button if app.platformName() == "offscreen" else app.widgetAt(position)
    assert target is button
    QTest.mouseClick(target, Qt.MouseButton.LeftButton, pos=target.mapFromGlobal(position))


def _assert_tip_near_button(tip: TeachingTip, button: HelpHintButton) -> None:
    bubble_rect = QRect(tip.bubble.mapToGlobal(QPoint()), tip.bubble.size())
    button_rect = QRect(button.mapToGlobal(QPoint()), button.size())
    gap = (
        button_rect.top() - bubble_rect.bottom()
        if bubble_rect.bottom() < button_rect.top()
        else bubble_rect.top() - button_rect.bottom()
    )
    assert 0 < gap <= button.height() // 2


def _assert_unwrapped_lines(label: QLabel, line_count: int) -> None:
    """Reject an extra wrapped line without depending on one platform's font padding."""
    spacing = label.fontMetrics().lineSpacing()
    assert spacing > 0
    assert label.height() < spacing * (line_count + 1)


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
    host.move(40, 0)
    host.show()
    qapp.processEvents()
    try:
        _enter(button)
        _wait_for_hover()
        tips = _visible_tips(host)
        assert len(tips) == 1
        _assert_tip_near_button(tips[0], button)

        _assert_button_input_clear(qapp, button)
        host.move(60, 240)
        host.resize(host.width() + 40, host.height() + 20)
        qapp.processEvents()
        _assert_tip_near_button(tips[0], button)

        _click_button_at_position(qapp, button)
        qapp.processEvents()
        assert _visible_tips(host) == []

        _enter(button)
        _wait_for_hover()
        assert _visible_tips(host) == []

        _click_button_at_position(qapp, button)
        qapp.processEvents()
        assert _visible_tips(host) == []

        _leave(button)
        _enter(button)
        _wait_for_hover()
        reopened = _visible_tips(host)
        assert len(reopened) == 1
    finally:
        _cleanup(host)


def test_help_tip_keeps_each_sentence_on_one_line(qapp: QApplication) -> None:
    sentence = "W" * 180
    view = _HelpTipView(f"{sentence}\nshort")
    label = view.contentLabel
    view.show()
    qapp.processEvents()
    assert label.width() >= label.fontMetrics().horizontalAdvance(sentence)
    _assert_unwrapped_lines(label, 2)
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


def test_template_source_hint_targets_its_own_row(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(editor_module, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(editor_module, "TEMPLATES_DIR", tmp_path / "templates")
    editor = ConfigEditorWidget()
    editor.resize(960, 650)
    editor.move(40, 100)
    editor.show()
    qapp.processEvents()
    try:
        buttons = {button.help_key: button for button in editor.findChildren(HelpHintButton)}
        source = buttons["config.help.template_source"]
        coords = buttons["config.help.template_coords"]
        scroll = editor.user_detail_card.findChild(QScrollArea)
        assert scroll is not None
        scroll.ensureWidgetVisible(source)
        qapp.processEvents()
        _enter(source)
        _wait_for_hover()
        tips = _visible_tips(editor)
        assert len(tips) == 1
        tip = tips[0]
        _assert_tip_near_button(tip, source)
        arrow_y = tip.bubble.mapToGlobal(QPoint(0, tip.bubble.height() - 1)).y()
        source_y = source.mapToGlobal(source.rect().center()).y()
        coords_y = coords.mapToGlobal(coords.rect().center()).y()
        assert abs(arrow_y - source_y) < abs(arrow_y - coords_y)
        _click_button_at_position(qapp, source)
        qapp.processEvents()
        assert _visible_tips(editor) == []
    finally:
        _cleanup(editor)


@pytest.mark.parametrize("same_window", [True, False])
def test_config_scroll_dismisses_only_same_window_help(
    qapp: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    same_window: bool,
) -> None:
    monkeypatch.setattr(editor_module, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(editor_module, "TEMPLATES_DIR", tmp_path / "templates")
    editor = ConfigEditorWidget()
    editor.resize(960, 600)
    editor.show()
    scrolling_editor = editor if same_window else ConfigEditorWidget()
    scrolling_editor.resize(960, 600)
    scrolling_editor.show()
    qapp.processEvents()
    try:
        proxy = next(button for button in editor.findChildren(HelpHintButton) if button.help_key == "config.help.proxy")
        _enter(proxy)
        _wait_for_hover()
        assert len(_visible_tips(editor)) == 1

        scroll = scrolling_editor.user_detail_card.findChild(QScrollArea)
        assert scroll is not None
        bar = scroll.verticalScrollBar()
        assert bar is not None
        assert bar.maximum() > bar.value()
        bar.setValue(bar.maximum())
        qapp.processEvents()
        assert len(_visible_tips(editor)) == (0 if same_window else 1)
    finally:
        if scrolling_editor is not editor:
            _cleanup(scrolling_editor)
        _cleanup(editor)
