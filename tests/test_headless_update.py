import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import app.__main__ as entrypoint
from app.update.headless import try_install_headless_update


def test_headless_update_prepares_and_restarts_headless() -> None:
    info = MagicMock()
    info.manifest.version = "1.2.3"
    prepared = MagicMock()
    service = MagicMock()
    service.check.return_value = info
    service.prepare.return_value = prepared

    with (
        patch("app.update.headless.IS_FROZEN", True),
        patch("app.update.headless.Config.load", return_value=SimpleNamespace(check_update=True)),
        patch("app.update.headless.UpdateService", return_value=service) as service_type,
    ):
        assert try_install_headless_update()

    service_type.cleanup_old_helpers.assert_called_once_with()
    service.prepare.assert_called_once()
    service.launch_helper.assert_called_once_with(prepared, headless=True)


def test_packaged_no_gui_runs_painter_when_no_update_is_available(tmp_path: Path) -> None:
    ready_file = tmp_path / "transaction" / "ready"
    with (
        patch.object(
            sys,
            "argv",
            ["wplace-auto-painter", "--no-gui", "--update-ready-file", str(ready_file)],
        ),
        patch.object(entrypoint, "IS_FROZEN", True),
        patch.object(entrypoint, "ensure_runtime_directories"),
        patch("app.config.export_config_schema"),
        patch("app.update.headless.try_install_headless_update", return_value=False),
        patch("app.wplace.run_painter") as run_painter,
        patch("anyio.run") as anyio_run,
    ):
        entrypoint.main()

    anyio_run.assert_called_once_with(run_painter)

    assert ready_file.read_text(encoding="utf-8") == "ready\n"


def test_packaged_no_gui_exits_after_launching_update() -> None:
    with (
        patch.object(sys, "argv", ["wplace-auto-painter", "--no-gui"]),
        patch.object(entrypoint, "IS_FROZEN", True),
        patch.object(entrypoint, "ensure_runtime_directories"),
        patch("app.config.export_config_schema"),
        patch("app.update.headless.try_install_headless_update", return_value=True),
        patch("app.wplace.run_painter") as run_painter,
        patch("anyio.run") as anyio_run,
    ):
        entrypoint.main()

    anyio_run.assert_not_called()
    run_painter.assert_not_called()
