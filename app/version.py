import functools
import json
import shutil
import subprocess
import tomllib
from dataclasses import dataclass

from app.const import ASSETS_DIR, IS_FROZEN, PROJECT_ROOT

BUILD_INFO_FILE = ASSETS_DIR / "build_info.json"
UNKNOWN_VERSION = "unknown"
SHORT_COMMIT_LENGTH = 7
UPDATER_PROTOCOL = 1


@dataclass(frozen=True)
class BuildInfo:
    version: str
    tag: str
    commit: str | None
    updater_protocol: int


@functools.cache
def find_git() -> str | None:
    if IS_FROZEN:
        return None
    return shutil.which("git")


def run_git(*args: str) -> subprocess.CompletedProcess[str] | None:
    if not (git := find_git()):
        return None

    try:
        return subprocess.run(  # noqa: S603
            [git, *args],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
    except OSError:
        return None


def _read_project_version() -> str:
    try:
        with PROJECT_ROOT.joinpath("pyproject.toml").open("rb") as file:
            data = tomllib.load(file)
        version = data["project"]["version"]
    except OSError, KeyError, TypeError, tomllib.TOMLDecodeError:
        return UNKNOWN_VERSION
    return version if isinstance(version, str) and version else UNKNOWN_VERSION


def _read_git_commit() -> str | None:
    process = run_git("rev-parse", "HEAD")
    if process is None or process.returncode != 0:
        return None
    commit = process.stdout.strip()
    return commit or None


def _read_frozen_build_info() -> BuildInfo | None:
    try:
        data = json.loads(BUILD_INFO_FILE.read_text("utf-8"))
        version = data["version"]
        tag = data["tag"]
        commit = data.get("commit")
        updater_protocol = data["updater_protocol"]
    except OSError, json.JSONDecodeError, KeyError, TypeError:
        return None

    if not isinstance(version, str) or not version or not isinstance(tag, str) or not tag:
        return None
    if commit is not None and not isinstance(commit, str):
        return None
    if not isinstance(updater_protocol, int) or updater_protocol < 1:
        return None
    return BuildInfo(version, tag, commit or None, updater_protocol)


@functools.cache
def get_build_info() -> BuildInfo | None:
    if IS_FROZEN:
        return _read_frozen_build_info()

    version = _read_project_version()
    return BuildInfo(version, f"v{version}", _read_git_commit(), UPDATER_PROTOCOL)


def get_commit_hash() -> str | None:
    build_info = get_build_info()
    return build_info.commit if build_info else None


def get_app_version() -> str:
    build_info = get_build_info()
    return build_info.version if build_info else UNKNOWN_VERSION


def get_version_display() -> str:
    version = get_app_version()
    commit = get_commit_hash()
    return f"v{version} ({commit[:SHORT_COMMIT_LENGTH]})" if commit else f"v{version}"
