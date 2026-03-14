import shutil
import subprocess
from pathlib import Path

from PyInstaller.building.api import EXE, PYZ
from PyInstaller.building.build_main import Analysis

ROOT = Path.cwd()
ICON = ROOT.joinpath("app", "assets", "gui.ico")


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
    ROOT.joinpath("app", "assets", ".git_commit_hash").write_text(commit_hash, encoding="utf-8")


def build_main_app() -> None:
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

    EXE(
        pyz,
        a.scripts,
        a.binaries,
        a.datas,
        [],
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


write_git_commit_hash()
build_main_app()
