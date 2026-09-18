import os
from collections.abc import Iterator
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QWidget

import app.gui.config.editor as editor_module
import app.wplace as wplace_module
from app.gui.config.area_editor_dialog import AreaEditorDialog
from app.gui.main_window import MainWindow
from app.gui.runtime import TaskRuntime
from app.gui.tray_icon import AppTrayIcon


@pytest.fixture
def qt_app() -> Iterator[QApplication]:
    app_instance = QApplication.instance()
    app = app_instance if isinstance(app_instance, QApplication) else QApplication([])
    yield app
    app.processEvents()


def _write_image(path: Path, color: Qt.GlobalColor) -> None:
    image = QImage(20, 20, QImage.Format.Format_ARGB32)
    image.fill(color)
    assert image.save(str(path))


def test_area_editor_resets_selection_when_image_changes(
    qt_app: QApplication,
    tmp_path: Path,
) -> None:
    old_image = tmp_path / "old.png"
    new_image = tmp_path / "new.png"
    _write_image(old_image, Qt.GlobalColor.red)
    _write_image(new_image, Qt.GlobalColor.blue)

    host = QWidget()
    host.resize(900, 700)
    dialog = AreaEditorDialog(host, image_path=str(old_image), selected_area=(2, 3, 4, 5))
    try:
        dialog._image_label.set_image(str(new_image))

        assert dialog.validate()
        assert dialog.result_image_path == str(new_image)
        assert dialog.result_area is None
    finally:
        dialog.deleteLater()
        host.deleteLater()
        qt_app.processEvents()


def test_area_editor_rejects_invalid_replacement_image(
    qt_app: QApplication,
    tmp_path: Path,
) -> None:
    old_image = tmp_path / "old.png"
    invalid_image = tmp_path / "invalid.txt"
    _write_image(old_image, Qt.GlobalColor.red)
    invalid_image.write_text("not an image", encoding="utf-8")

    host = QWidget()
    host.resize(900, 700)
    dialog = AreaEditorDialog(host, image_path=str(old_image), selected_area=(2, 3, 4, 5))
    try:
        dialog._image_label.set_image(str(invalid_image))

        assert not dialog.validate()
        assert dialog.result_image_path is None
        assert dialog.result_area is None
    finally:
        dialog.deleteLater()
        host.deleteLater()
        qt_app.processEvents()


def test_empty_image_preview_opens_file_picker(
    qt_app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    selected_image = tmp_path / "selected.png"
    _write_image(selected_image, Qt.GlobalColor.green)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(selected_image), ""),
    )

    host = QWidget()
    host.resize(900, 700)
    host.show()
    dialog = AreaEditorDialog(host, image_path=None, selected_area=None)
    dialog.show()
    qt_app.processEvents()
    try:
        QTest.mouseClick(dialog._image_label, Qt.MouseButton.LeftButton)
        qt_app.processEvents()

        assert dialog.result_image_path == str(selected_image)
        assert dialog._image_label.filepath == str(selected_image)
    finally:
        dialog.deleteLater()
        host.deleteLater()
        qt_app.processEvents()


def test_main_window_loads_saved_geometry_only_once(
    qt_app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(editor_module, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(editor_module, "TEMPLATES_DIR", tmp_path / "templates")
    window = MainWindow(
        QIcon(),
        on_start=lambda: None,
        on_stop=lambda: None,
        on_save=lambda: None,
        on_update=lambda: None,
        on_exit=lambda: None,
    )
    load_count = 0

    def load_properties() -> None:
        nonlocal load_count
        load_count += 1

    monkeypatch.setattr(window, "_load_window_properties", load_properties)
    try:
        window.show_main_window()
        window.hide()
        window.show_main_window()
        qt_app.processEvents()

        assert load_count == 1
    finally:
        window.allow_exit()
        window.close()
        window.deleteLater()
        qt_app.processEvents()


def test_runtime_reports_failed_painter_as_error(
    qt_app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failed_painter() -> bool:
        return False

    monkeypatch.setattr(wplace_module, "run_painter", failed_painter)
    runtime = TaskRuntime()
    states: list[str] = []
    runtime.signals.state_changed.connect(states.append)

    assert runtime.start()
    runtime.join(timeout=5)
    qt_app.processEvents()

    assert states == ["running", "error"]


def test_tray_actions_follow_runtime_state(qt_app: QApplication) -> None:
    tray = AppTrayIcon(QIcon())
    tray.setup_menu(lambda: None, lambda: None, lambda: None, lambda: None)
    try:
        assert tray.start_action.isEnabled()
        assert not tray.stop_action.isEnabled()

        tray.set_runtime_state("running")
        assert not tray.start_action.isEnabled()
        assert tray.stop_action.isEnabled()

        tray.set_runtime_state("stopping")
        assert not tray.start_action.isEnabled()
        assert not tray.stop_action.isEnabled()
    finally:
        tray.deleteLater()
        qt_app.processEvents()
