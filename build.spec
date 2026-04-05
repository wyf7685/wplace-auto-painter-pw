import contextlib
import os
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.building.datastruct import Target

ROOT = Path.cwd()
ICON = ROOT.joinpath("app", "assets", "icon", "gui.ico")


def write_git_commit_hash() -> None:
    git = shutil.which("git")
    if git is None:
        raise RuntimeError("Git is not available")

    p = subprocess.run(  # noqa: S603
        [git, "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    commit_hash = p.stdout.strip()

    path = ROOT.joinpath("app", "assets", ".git_commit_hash")
    existing_hash = path.read_text("utf-8").strip() if path.is_file() else None
    if existing_hash != commit_hash:
        path.write_text(commit_hash, encoding="utf-8")


@contextlib.contextmanager
def ignore_env_path() -> Iterator[None]:
    env_path = os.environ.pop("PATH", "")
    os.environ["PATH"] = ""
    try:
        yield
    finally:
        os.environ["PATH"] = env_path


def build_main_app() -> Target:
    with ignore_env_path():
        a = Analysis(
            ["main.py"],
            pathex=[],
            binaries=[],
            datas=[("app/assets", "assets")],
            hiddenimports=[],
            hookspath=[],
            hooksconfig={},
            runtime_hooks=[],
            excludes=[],
            noarchive=False,
            optimize=0,
        )

    pyz = PYZ(a.pure)
    exe = EXE(
        pyz,
        a.scripts,
        [],
        exclude_binaries=True,
        name="wplace-auto-painter",
        icon=ICON,
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=True,
        upx_exclude=[],
        runtime_tmpdir=None,
        console=False,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
    )

    coll = COLLECT(
        exe,
        a.binaries,
        a.datas,
        strip=False,
        upx=True,
        upx_exclude=[],
        name="wplace-auto-painter",
    )

    return coll  # noqa: RET504


write_git_commit_hash()
build_main_app()
