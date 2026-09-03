# ruff: noqa: T201
import contextlib
import os
from collections.abc import Generator
from pathlib import Path

from PyInstaller.building.api import EXE, PYZ
from PyInstaller.building.build_main import Analysis

APP_NAME = "wplace-auto-painter-updater"
ROOT = Path.cwd()
ENTRYPOINT = ROOT / "app" / "update_helper.py"


@contextlib.contextmanager
def ignore_env_path() -> Generator[None]:
    if os.getenv("BUILD_CI") == "true":
        yield
        return

    env_path = os.environ.pop("PATH", "")
    os.environ["PATH"] = ""
    try:
        yield
    finally:
        os.environ["PATH"] = env_path


print("Building standalone update helper")
with ignore_env_path():
    analysis = Analysis(
        scripts=[ENTRYPOINT],
        pathex=[ROOT],
        binaries=[],
        datas=[],
        hiddenimports=[],
        hookspath=[],
        hooksconfig={},
        runtime_hooks=[],
        excludes=[],
        noarchive=False,
        optimize=0,
    )

pyz = PYZ(analysis.pure)
executable = EXE(
    pyz,
    analysis.scripts,
    analysis.binaries,
    analysis.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
