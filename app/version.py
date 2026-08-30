import functools
import shutil
import subprocess
from pathlib import Path

from app.const import ASSETS_DIR, IS_FROZEN
from app.utils.func import subprocess_options

PROJECT_ROOT = Path(__file__).resolve().parent.parent
COMMIT_HASH_FILE = ASSETS_DIR / ".git_commit_hash"
UNKNOWN_VERSION = "unknown"
SHORT_COMMIT_LENGTH = 7


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
            **subprocess_options(),
        )
    except OSError:
        return None


@functools.cache
def get_commit_hash() -> str | None:
    if IS_FROZEN:
        try:
            commit_hash = COMMIT_HASH_FILE.read_text("utf-8").strip()
        except OSError:
            return None
        return commit_hash or None

    process = run_git("rev-parse", "HEAD")
    if process is None or process.returncode != 0:
        return None

    commit_hash = process.stdout.strip()
    return commit_hash or None


def get_app_version() -> str:
    commit_hash = get_commit_hash()
    return commit_hash[:SHORT_COMMIT_LENGTH] if commit_hash else UNKNOWN_VERSION
