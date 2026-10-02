import json
import os
import subprocess
import sys
from collections.abc import Iterator
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import loguru
import pytest
from PySide6.QtWidgets import QApplication

import app.gui.config.editor as editor_module
import app.gui.state as state_module
from app.log import logger


@pytest.fixture
def qt_app() -> Iterator[QApplication]:
    app_instance = QApplication.instance()
    app = app_instance if isinstance(app_instance, QApplication) else QApplication([])
    yield app
    app.processEvents()


@pytest.fixture
def captured_logs() -> Iterator[list[loguru.Message]]:
    messages: list[loguru.Message] = []
    sink_id = logger.add(messages.append, diagnose=False, backtrace=False)
    try:
        yield messages
    finally:
        logger.remove(sink_id)


def test_corrupt_gui_state_logs_failure_and_restores_defaults(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    captured_logs: list[loguru.Message],
) -> None:
    state_file = tmp_path / "gui_state.json"
    state_file.write_text("{", encoding="utf-8")
    monkeypatch.setattr(state_module, "_GUI_STATE_FILE", state_file)
    monkeypatch.setattr(state_module.GUIState, "_instance", None)

    state = state_module.GUIState.load()

    assert state.main_window.top_left is None
    assert state.main_window.size is None
    assert len(captured_logs) == 1
    message = captured_logs[0]
    assert str(state_file) in message.record["message"]
    assert message.record["level"].name == "ERROR"
    exception = message.record["exception"]
    assert exception is not None
    assert exception.traceback is not None
    assert "ValidationError" in str(message)


def test_rejected_user_switch_logs_chained_failure_and_preserves_draft(
    qt_app: QApplication,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    captured_logs: list[loguru.Message],
) -> None:
    config_file = tmp_path / "config.json"
    config_file.write_text(
        json.dumps({"users": [{"identifier": "first-user"}, {"identifier": "second-user"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(editor_module, "CONFIG_FILE", config_file)
    editor = editor_module.ConfigEditorWidget()
    try:
        editor.user_detail_card.selected_area_edit.setText("invalid-area")
        editor.users_list.setCurrentRow(1)
        qt_app.processEvents()

        assert editor.users_list.currentRow() == 0
        assert editor.user_detail_card.identifier_edit.text() == "first-user"
        assert editor.user_detail_card.selected_area_edit.text() == "invalid-area"
        assert len(captured_logs) == 1
        message = captured_logs[0]
        assert str(config_file) in message.record["message"]
        assert "previous_user_row=0" in message.record["message"]
        assert "requested_user_row=1" in message.record["message"]
        exception = message.record["exception"]
        assert exception is not None
        assert exception.traceback is not None
        assert exception.value is not None
        assert isinstance(exception.value.__cause__, ValueError)
        assert "ValueError" in str(message)
        assert "_ConfigFieldError" in str(message)
    finally:
        editor.close()
        editor.deleteLater()
        qt_app.processEvents()


def test_default_file_sink_keeps_gui_traceback_without_credentials(tmp_path: Path) -> None:
    script = """
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
import app.const as constants
root = Path(sys.argv[1])
constants.LOGS_DIR = root / "logs"
constants.CONFIG_FILE = root / "config.json"
constants.TEMPLATES_DIR = root / "templates"
import app.gui.controller as controller_module
import app.gui.config.editor as editor_module
from app.log import logger
app = QApplication([])
constants.TEMPLATES_DIR.mkdir()
(constants.TEMPLATES_DIR / "template.png").write_bytes(b"template")
editor = editor_module.ConfigEditorWidget()
card = editor.user_detail_card
card.token_edit.setPlainText("private-test-token")
card.cf_clearance_edit.setPlainText("private-test-cookie")
card.file_id_edit.setText("template")
editor.proxy_edit.setText("http://private-test-user:private-test-password@localhost:8080")
editor.browser_cb.addItem("invalid-browser")
editor.browser_cb.setCurrentIndex(editor.browser_cb.count() - 1)
result = editor.save_to_disk(show_message=False)
assert not result.success
assert not constants.CONFIG_FILE.exists()
constants.CONFIG_FILE.write_text('{"users": [{"credentials": {"token": "private-load-token"}}]}')
assert not controller_module.Controller._auto_update_check_enabled()
assert controller_module.Controller._desktop_notifications_enabled()
logger.complete()
editor.close()
"""
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", script, str(tmp_path)],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        cwd=Path(__file__).resolve().parent.parent,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    log_files = list((tmp_path / "logs").glob("*.log"))
    assert len(log_files) == 1
    output = log_files[0].read_text(encoding="utf-8")
    assert "Traceback (most recent call last)" in output
    assert "ValidationError" in output
    assert "save_to_disk" in output
    assert str(tmp_path / "config.json") in output
    for secret in (
        "private-test-token",
        "private-test-cookie",
        "private-test-user",
        "private-test-password",
        "private-load-token",
    ):
        assert secret not in output
        assert secret not in result.stdout
