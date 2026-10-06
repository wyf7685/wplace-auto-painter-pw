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
import app.gui.logging.log_viewer as log_viewer_module
import app.gui.state as state_module
from app.gui.logging import AnsiLogViewer, LogEntry
from app.log import logger


@pytest.fixture
def qt_app() -> Iterator[QApplication]:
    app_instance = QApplication.instance()
    app = app_instance if isinstance(app_instance, QApplication) else QApplication([])
    yield app
    app.processEvents()


@pytest.fixture
def log_viewer(qt_app: QApplication, monkeypatch: pytest.MonkeyPatch) -> Iterator[AnsiLogViewer]:
    monkeypatch.setattr(log_viewer_module, "_MAX_BLOCK_COUNT", 8)
    viewer = AnsiLogViewer()
    try:
        yield viewer
    finally:
        viewer.close()
        viewer.deleteLater()
        qt_app.processEvents()


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


def test_log_filter_uses_numeric_levels_and_restores_colored_records(log_viewer: AnsiLogViewer) -> None:
    log_viewer.append_entry(LogEntry(text="info contains [ERROR]", level_no=20))
    log_viewer.append_entry(LogEntry(text="success", level_no=25))
    log_viewer.append_entry(LogEntry(text="warning", level_no=30))
    log_viewer.append_entry(LogEntry(text="\x1b[31mfailure\ntraceback-detail\x1b[0m", level_no=40))
    log_viewer.append_entry(LogEntry(text="critical", level_no=50))
    document = log_viewer._text.document()
    error_color = document.find("failure").charFormat().foreground().color()
    assert error_color != document.find("info").charFormat().foreground().color()

    log_viewer._level_filter.setCurrentText("WARNING")
    assert log_viewer._text.toPlainText() == "warning\nfailure\ntraceback-detail\ncritical"
    log_viewer.append_entry(LogEntry(text="hidden debug", level_no=10))
    log_viewer._level_filter.setCurrentText("INFO")
    assert log_viewer._text.toPlainText() == (
        "info contains [ERROR]\nsuccess\nwarning\nfailure\ntraceback-detail\ncritical"
    )
    assert document.find("failure").charFormat().foreground().color() == error_color
    log_viewer._level_filter.setCurrentIndex(0)
    assert log_viewer._text.toPlainText().endswith("critical\nhidden debug")


def test_clear_discards_hidden_history_and_resets_the_first_visible_record(log_viewer: AnsiLogViewer) -> None:
    log_viewer._level_filter.setCurrentText("ERROR")
    log_viewer.append_entry(LogEntry(text="hidden", level_no=10))
    log_viewer.append_entry(LogEntry(text="visible", level_no=40))
    assert log_viewer._text.toPlainText() == "visible"
    log_viewer.clear()
    log_viewer._level_filter.setCurrentIndex(0)
    assert log_viewer._text.toPlainText() == ""
    log_viewer.append_entry(LogEntry(text="new record", level_no=20))
    assert log_viewer._text.toPlainText() == "new record"


def test_history_budget_evicts_whole_records_even_when_new_records_are_hidden(log_viewer: AnsiLogViewer) -> None:
    log_viewer._level_filter.setCurrentText("WARNING")
    log_viewer.append_entry(LogEntry(text="first\r\nsecond\rthird\u2029fourth\nfifth\u2028sixth", level_no=40))
    log_viewer.append_entry(LogEntry(text="warning", level_no=30))
    log_viewer.append_entry(LogEntry(text="debug-1\ndebug-2", level_no=10))
    assert log_viewer._text.toPlainText() == "first\nsecond\nthird\nfourth\nfifth\nsixth\nwarning"

    log_viewer.append_entry(LogEntry(text="new debug", level_no=10))
    assert log_viewer._text.toPlainText() == "warning"
    log_viewer._level_filter.setCurrentIndex(0)
    assert log_viewer._text.toPlainText() == "warning\ndebug-1\ndebug-2\nnew debug"

    log_viewer._level_filter.setCurrentText("WARNING")
    log_viewer.append_entry(LogEntry(text="a\nb\nc\nd\ne", level_no=10))
    assert log_viewer._text.toPlainText() == ""
    log_viewer._level_filter.setCurrentIndex(0)
    assert log_viewer._text.toPlainText() == "debug-1\ndebug-2\nnew debug\na\nb\nc\nd\ne"


def test_oversized_record_keeps_document_limit_and_expires_as_a_whole(log_viewer: AnsiLogViewer) -> None:
    log_viewer.append_entry(LogEntry(text="\n".join(f"line-{index}" for index in range(9)), level_no=40))
    expected = "\n".join(f"line-{index}" for index in range(1, 9))
    assert log_viewer._text.toPlainText() == expected
    log_viewer._level_filter.setCurrentText("ERROR")
    assert log_viewer._text.toPlainText() == expected
    log_viewer.append_entry(LogEntry(text="next record", level_no=5))
    assert log_viewer._text.toPlainText() == ""
    log_viewer._level_filter.setCurrentIndex(0)
    assert log_viewer._text.toPlainText() == "next record"


def test_gui_captures_trace_independently_of_console_level(tmp_path: Path) -> None:
    script = """
import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
import app.const as constants
constants.LOGS_DIR = Path(sys.argv[1]) / "logs"
constants.CONFIG_FILE = Path(sys.argv[1]) / "config.json"
import app.log as log_module
from app.log import logger
from app.gui.logging import AnsiLogViewer, LogBridge
log_module.get_log_level = lambda: 50
app = QApplication([])
viewer = AnsiLogViewer()
bridge = LogBridge()
bridge.new_entry.connect(viewer.append_entry)
bridge.start()
try:
    logger.trace("trace-event")
    logger.debug("debug-event")
    logger.complete()
    app.processEvents()
    assert "trace-event" in viewer._text.toPlainText()
    assert "debug-event" in viewer._text.toPlainText()
    viewer._level_filter.setCurrentText("ERROR")
    assert viewer._text.toPlainText() == ""
    viewer._level_filter.setCurrentText("TRACE")
    assert "trace-event" in viewer._text.toPlainText()
    assert "debug-event" in viewer._text.toPlainText()
finally:
    bridge.stop()
    viewer.close()
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
