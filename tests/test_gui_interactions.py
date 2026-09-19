import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QImage
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QFileDialog, QWidget

import app.gui.config.editor as editor_module
import app.gui.controller as controller_module
import app.wplace as wplace_module
from app.gui.config.area_editor_dialog import AreaEditorDialog
from app.gui.controller import Controller
from app.gui.main_window import MainWindow
from app.gui.runtime import TaskRuntime
from app.gui.tray_icon import AppTrayIcon
from app.i18n import tr


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


def test_empty_image_preview_opens_file_picker_from_config_editor(
    qt_app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(editor_module, "CONFIG_FILE", tmp_path / "config.json")
    monkeypatch.setattr(editor_module, "TEMPLATES_DIR", tmp_path / "templates")
    selected_image = tmp_path / "selected.png"
    _write_image(selected_image, Qt.GlobalColor.green)
    monkeypatch.setattr(
        QFileDialog,
        "getOpenFileName",
        lambda *_args, **_kwargs: (str(selected_image), ""),
    )

    editor = editor_module.ConfigEditorWidget()
    editor.show()
    qt_app.processEvents()

    def choose_image(dialog: AreaEditorDialog) -> int:
        dialog.show()
        qt_app.processEvents()
        QTest.mouseClick(dialog._image_label, Qt.MouseButton.LeftButton)
        qt_app.processEvents()
        assert dialog.validate()
        return int(dialog.DialogCode.Accepted)

    monkeypatch.setattr(AreaEditorDialog, "exec", choose_image)
    try:
        editor.user_detail_card.edit_area_btn.click()

        assert editor.user_detail_card.template_source_edit.text() == str(selected_image)
        assert editor.user_detail_card.file_id_edit.text() == "selected"
    finally:
        editor.close()
        editor.deleteLater()
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
    async def failed_painter(_on_user_failed: Any = None) -> bool:
        return False

    monkeypatch.setattr(wplace_module, "run_painter", failed_painter)
    runtime = TaskRuntime()
    states: list[str] = []
    runtime.signals.state_changed.connect(states.append)

    assert runtime.start()
    runtime.join(timeout=5)
    qt_app.processEvents()

    assert states == ["running", "error"]


def test_runtime_emits_user_failure_without_error_state(
    qt_app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def partially_failed_painter(on_user_failed: Any = None) -> bool:
        assert on_user_failed is not None
        on_user_failed("failed-user")
        return True

    monkeypatch.setattr(wplace_module, "run_painter", partially_failed_painter)
    runtime = TaskRuntime()
    states: list[str] = []
    failed_users: list[str] = []
    runtime.signals.state_changed.connect(states.append)
    runtime.signals.user_failed.connect(failed_users.append)

    assert runtime.start()
    runtime.join(timeout=5)
    qt_app.processEvents()

    assert failed_users == ["failed-user"]
    assert states == ["running", "stopped"]


def test_visible_user_failure_shows_warning(qt_app: QApplication) -> None:
    window = QWidget()
    window.show()
    controller: Any = object.__new__(Controller)
    controller.window = window

    try:
        Controller._handle_user_failure(controller, "failed-user")
        qt_app.processEvents()

        info_bars = window.findChildren(controller_module.InfoBar)
        assert len(info_bars) == 1
        actual = "".join(info_bars[0].contentLabel.text().split())
        expected = "".join(tr("controller.runtime.user_failed", identifier="failed-user").split())
        assert actual == expected
    finally:
        window.close()
        window.deleteLater()
        qt_app.processEvents()


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


def test_update_is_blocked_while_runtime_is_running(qt_app: QApplication) -> None:
    class UpdaterStub:
        state = "ready"

    class RuntimeStub:
        is_running = True

    window = QWidget()
    window.show()
    controller: Any = object.__new__(Controller)
    controller.updater = UpdaterStub()
    controller.runtime = RuntimeStub()
    controller.window = window
    controller._install_update = lambda: pytest.fail("Update installation must not start while painting")

    try:
        Controller.handle_update_action(controller)
        qt_app.processEvents()

        info_bars = window.findChildren(controller_module.InfoBar)
        assert len(info_bars) == 1
        assert info_bars[0].contentLabel.text() == tr("controller.update_blocked.content")
    finally:
        window.close()
        window.deleteLater()
        qt_app.processEvents()


def test_update_helper_waits_for_unsaved_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    class UpdaterStub:
        state = "ready"

        def __init__(self) -> None:
            self.install_calls = 0
            self.emit_calls = 0

        def install(self) -> None:
            self.install_calls += 1

        def emit_current_state(self) -> None:
            self.emit_calls += 1

    updater = UpdaterStub()
    controller: Any = object.__new__(Controller)
    controller.updater = updater
    controller._update_exit_preapproved = False
    monkeypatch.setattr(controller, "_confirm_unsaved_changes", lambda: False)

    Controller._install_update(controller)

    assert updater.install_calls == 0
    assert updater.emit_calls == 1
    assert not controller._update_exit_preapproved


def test_update_restart_reuses_completed_confirmation(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []
    confirmation_count = 0
    controller: Any = object.__new__(Controller)

    def confirm_unsaved_changes() -> bool:
        nonlocal confirmation_count
        confirmation_count += 1
        return True

    class UpdaterStub:
        state = "ready"

        def install(self) -> None:
            self.state = "applying"
            events.append("install")
            Controller.exit_app(controller)

    class RuntimeStub:
        def stop(self) -> None:
            events.append("stop")

    class WindowStub:
        def allow_exit(self) -> None:
            events.append("allow_exit")

    class ApplicationStub:
        def quit(self) -> None:
            events.append("quit")

    controller.updater = UpdaterStub()
    controller.runtime = RuntimeStub()
    controller.window = WindowStub()
    controller.app = ApplicationStub()
    controller._update_exit_preapproved = False
    monkeypatch.setattr(controller, "_confirm_unsaved_changes", confirm_unsaved_changes)

    Controller._install_update(controller)

    assert confirmation_count == 1
    assert events == ["install", "stop", "allow_exit", "quit"]
    assert not controller._update_exit_preapproved


def test_tray_hint_honors_disabled_notifications(monkeypatch: pytest.MonkeyPatch) -> None:
    class TrayStub:
        def __init__(self) -> None:
            self.messages: list[tuple[object, ...]] = []

        def showMessage(self, *args: object) -> None:  # noqa: N802
            self.messages.append(args)

    tray = TrayStub()
    controller: Any = object.__new__(Controller)
    controller.tray = tray
    controller._tray_available = True
    controller._tray_hint_shown = False
    monkeypatch.setattr(
        controller_module.Config,
        "load",
        staticmethod(lambda: type("ConfigStub", (), {"disable_notifications": True})()),
    )

    Controller._show_tray_hint(controller)

    assert tray.messages == []
    assert not controller._tray_hint_shown
