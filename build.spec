import subprocess
from pathlib import Path

from PyInstaller.building.api import EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_data_files

ROOT = Path.cwd()
ICON = ROOT.joinpath("app", "assets", "gui.ico")
ROOT.joinpath("app", "assets", ".git_commit_hash").write_text(
    subprocess.run(
        ["git", "rev-parse", "HEAD"],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip(),
    encoding="utf-8",
)


# Build config-gui
def build_config_gui() -> None:
    a = Analysis(
        ["gui_main.py"],
        pathex=[],
        binaries=[],
        datas=[
            ("app/assets", "assets"),
            *collect_data_files("tarina"),
        ],
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
        name="config-gui",
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


# Build main app
def build_main_app() -> None:
    a = Analysis(
        ["main.py"],
        pathex=[],
        binaries=[],
        datas=[
            ("app/assets", "assets"),
            *collect_data_files("tarina"),
        ],
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


build_config_gui()
build_main_app()
