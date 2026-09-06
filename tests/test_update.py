import json
import tempfile
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import httpx
import pytest

from app.update.client import ReleaseClient
from app.update.model import PackageManifest, UpdateError
from app.update.service import _extract_archive
from app.update_helper import UpdatePlan, apply_update, load_plan
from app.version import BuildInfo

MANAGED_ENTRIES = ("wplace-auto-painter.exe", "_internal", "package-manifest.json")


def write_package(root: Path, marker: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    root.joinpath("wplace-auto-painter.exe").write_text(f"exe-{marker}", encoding="utf-8")
    root.joinpath("_internal").mkdir()
    root.joinpath("_internal", "runtime.txt").write_text(marker, encoding="utf-8")
    root.joinpath("package-manifest.json").write_text(f"manifest-{marker}", encoding="utf-8")


def make_plan(root: Path) -> UpdatePlan:
    install_dir = root / "install"
    update_root = install_dir / "data" / "updates" / "transaction"
    staging_dir = update_root / "staging" / "wplace-auto-painter"
    write_package(install_dir, "old")
    write_package(staging_dir, "new")
    install_dir.joinpath("data").mkdir(parents=True, exist_ok=True)
    install_dir.joinpath("data", "config.json").write_text("preserved", encoding="utf-8")
    return UpdatePlan(
        parent_pid=1,
        install_dir=install_dir,
        staging_dir=staging_dir,
        backup_dir=update_root / "backup",
        executable="wplace-auto-painter.exe",
        ready_file=update_root / "ready",
        log_file=install_dir / "data" / "updates" / "updater.log",
        old_managed_entries=MANAGED_ENTRIES,
        new_managed_entries=MANAGED_ENTRIES,
        readiness_timeout=1.0,
    )


def test_package_manifest_rejects_user_data_as_managed_entry() -> None:
    with pytest.raises(ValueError, match="Unsafe managed entry"):
        PackageManifest(
            schema_version=1,
            version="1.0.0",
            tag="v1.0.0",
            commit="a" * 40,
            updater_protocol=1,
            executable="wplace-auto-painter.exe",
            managed_entries=["wplace-auto-painter.exe", "data"],
        )


def test_update_plan_rejects_non_boolean_headless_mode() -> None:
    with tempfile.TemporaryDirectory() as directory:
        plan = make_plan(Path(directory))
        plan_path = plan.ready_file.parent / "update-plan.json"
        plan_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "parent_pid": plan.parent_pid,
                    "install_dir": str(plan.install_dir),
                    "staging_dir": str(plan.staging_dir),
                    "backup_dir": str(plan.backup_dir),
                    "executable": plan.executable,
                    "ready_file": str(plan.ready_file),
                    "log_file": str(plan.log_file),
                    "old_managed_entries": plan.old_managed_entries,
                    "new_managed_entries": plan.new_managed_entries,
                    "readiness_timeout": plan.readiness_timeout,
                    "headless": "yes",
                }
            ),
            encoding="utf-8",
        )

        helper_path = plan.log_file.parent / "helper.exe"
        with (
            patch("app.update_helper.sys.executable", str(helper_path)),
            pytest.raises(TypeError, match="headless"),
        ):
            load_plan(plan_path)


def test_archive_extraction_rejects_parent_directory_escape() -> None:
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        archive = root / "update.zip"
        with zipfile.ZipFile(archive, "w") as file:
            file.writestr("../escaped.txt", "unsafe")

        with pytest.raises(UpdateError), patch("app.update.service.MAX_EXPANSION_RATIO", 100):
            _extract_archive(archive, root / "staging", archive.stat().st_size)
        assert not root.joinpath("escaped.txt").exists()


def test_helper_success_replaces_managed_entries_and_preserves_data() -> None:
    with tempfile.TemporaryDirectory() as directory:
        plan = replace(make_plan(Path(directory)), headless=True)
        process = MagicMock()

        def mark_ready(*_args: object) -> None:
            plan.ready_file.write_text("ready", encoding="utf-8")

        with (
            patch("app.update_helper.wait_for_process_exit"),
            patch("app.update_helper._launch", return_value=process) as launch,
            patch("app.update_helper._wait_until_ready", side_effect=mark_ready),
        ):
            apply_update(plan)

        assert plan.install_dir.joinpath("wplace-auto-painter.exe").read_text(encoding="utf-8") == "exe-new"
        assert plan.install_dir.joinpath("_internal", "runtime.txt").read_text(encoding="utf-8") == "new"
        assert plan.install_dir.joinpath("data", "config.json").read_text(encoding="utf-8") == "preserved"
        assert not plan.backup_dir.exists()
        launch.assert_called_once_with(
            plan.install_dir / plan.executable,
            "--no-gui",
            "--update-ready-file",
            str(plan.ready_file),
        )


def test_helper_failed_new_version_restores_old_package() -> None:
    with tempfile.TemporaryDirectory() as directory:
        plan = replace(make_plan(Path(directory)), headless=True)
        process = MagicMock()
        with (
            patch("app.update_helper.wait_for_process_exit"),
            patch("app.update_helper._launch", return_value=process) as launch,
            patch("app.update_helper._wait_until_ready", side_effect=RuntimeError("startup failed")),
            patch("app.update_helper._terminate"),
            pytest.raises(RuntimeError),
        ):
            apply_update(plan)

        assert plan.install_dir.joinpath("wplace-auto-painter.exe").read_text(encoding="utf-8") == "exe-old"
        assert plan.install_dir.joinpath("_internal", "runtime.txt").read_text(encoding="utf-8") == "old"
        assert plan.install_dir.joinpath("data", "config.json").read_text(encoding="utf-8") == "preserved"
        assert launch.call_args_list == [
            call(
                plan.install_dir / plan.executable,
                "--no-gui",
                "--update-ready-file",
                str(plan.ready_file),
            ),
            call(plan.install_dir / plan.executable, "--no-gui"),
        ]


def test_release_client_selects_newer_platform_asset() -> None:
    archive_name = "wplace-auto-painter-v1.1.0-windows-x86_64.zip"
    manifest = {
        "schema_version": 1,
        "version": "1.1.0",
        "tag": "v1.1.0",
        "commit": "b" * 40,
        "updater_protocol": 1,
        "assets": {
            "windows-x86_64": {
                "name": archive_name,
                "size": 123,
                "sha256": "c" * 64,
            }
        },
    }

    def handle_request(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/releases/latest"):
            return httpx.Response(
                200,
                json={
                    "tag_name": "v1.1.0",
                    "html_url": "https://github.test/releases/v1.1.0",
                    "draft": False,
                    "prerelease": False,
                    "assets": [
                        {
                            "name": "update-manifest.json",
                            "browser_download_url": "https://downloads.test/update-manifest.json",
                            "size": 100,
                            "state": "uploaded",
                        },
                        {
                            "name": archive_name,
                            "browser_download_url": f"https://downloads.test/{archive_name}",
                            "size": 123,
                            "state": "uploaded",
                        },
                    ],
                },
            )
        return httpx.Response(200, json=manifest)

    http_client = httpx.Client(transport=httpx.MockTransport(handle_request))
    release_client = ReleaseClient()
    local = BuildInfo("1.0.0", "v1.0.0", "a" * 40, 1)
    with (
        patch.object(release_client, "_client", return_value=http_client),
        patch("app.update.client.current_platform_key", return_value="windows-x86_64"),
    ):
        update = release_client.check(local)

    assert update is not None
    assert update.manifest.version == "1.1.0"
    assert update.asset.name == archive_name
