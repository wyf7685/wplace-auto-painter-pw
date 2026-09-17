import argparse
import json
import subprocess
from collections import defaultdict
from pathlib import Path

import pytest

from scripts import release


def make_release_assets(root: Path) -> list[release.ReleaseAsset]:
    version = release.read_project_version()
    for platform_key, suffix in release.PLATFORM_SUFFIXES.items():
        root.joinpath(f"{release.APP_NAME}-v{version}-{platform_key}{suffix}").write_bytes(platform_key.encode())
    root.joinpath("update-manifest.json").write_text("{}\n", encoding="utf-8")
    return release.get_release_assets(root)


def remote_asset(asset: release.ReleaseAsset) -> dict[str, object]:
    return {
        "name": asset.path.name,
        "size": asset.size,
        "digest": asset.digest,
        "state": "uploaded",
    }


def test_publish_release_retries_timeout_and_resumes_verified_assets(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assets = make_release_assets(tmp_path)
    manifest = next(asset for asset in assets if asset.path.name == "update-manifest.json")
    windows = next(asset for asset in assets if asset.path.suffix == ".zip")
    remote_assets = {manifest.path.name: remote_asset(manifest)}
    attempts: defaultdict[str, int] = defaultdict(int)
    state = {"published": False}

    def fake_run_gh(
        *arguments: str,
        check: bool = True,
        capture_output: bool = False,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del check, capture_output
        if arguments[:2] == ("release", "view"):
            payload = {"isDraft": not state["published"], "assets": list(remote_assets.values())}
            return subprocess.CompletedProcess(arguments, 0, json.dumps(payload), "")
        if arguments[:2] == ("release", "upload"):
            asset = next(item for item in assets if item.path == Path(arguments[3]))
            attempts[asset.path.name] += 1
            if asset == windows and attempts[asset.path.name] == 1:
                assert timeout is not None
                raise subprocess.TimeoutExpired(arguments, timeout)
            remote_assets[asset.path.name] = remote_asset(asset)
            return subprocess.CompletedProcess(arguments, 0, "", "")
        if arguments[:2] == ("release", "edit"):
            assert all(asset.path.name in remote_assets for asset in assets)
            state["published"] = True
            return subprocess.CompletedProcess(arguments, 0, "", "")
        raise AssertionError(f"Unexpected GitHub CLI call: {arguments}")

    monkeypatch.setattr(release, "run_gh", fake_run_gh)
    monkeypatch.setattr(release.time, "sleep", lambda _seconds: None)

    release.publish_release(argparse.Namespace(assets_dir=tmp_path, tag=f"v{release.read_project_version()}"))

    assert attempts[windows.path.name] == 2
    assert attempts[manifest.path.name] == 0
    assert state["published"] is True


def test_publish_release_does_not_publish_after_upload_retries_fail(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    make_release_assets(tmp_path)
    state = {"published": False}

    def fake_run_gh(
        *arguments: str,
        check: bool = True,
        capture_output: bool = False,
        timeout: int | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del check, capture_output
        if arguments[:2] == ("release", "view"):
            return subprocess.CompletedProcess(arguments, 0, json.dumps({"isDraft": True, "assets": []}), "")
        if arguments[:2] == ("release", "upload"):
            assert timeout is not None
            raise subprocess.TimeoutExpired(arguments, timeout)
        if arguments[:2] == ("release", "edit"):
            state["published"] = True
            return subprocess.CompletedProcess(arguments, 0, "", "")
        raise AssertionError(f"Unexpected GitHub CLI call: {arguments}")

    monkeypatch.setattr(release, "run_gh", fake_run_gh)
    monkeypatch.setattr(release.time, "sleep", lambda _seconds: None)

    with pytest.raises(RuntimeError, match="upload exhausted retries"):
        release.publish_release(argparse.Namespace(assets_dir=tmp_path, tag=f"v{release.read_project_version()}"))

    assert state["published"] is False
