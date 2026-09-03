# ruff: noqa: T201
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tomllib
from collections.abc import Generator
from pathlib import Path

ROOT = Path.cwd()
sys.path.insert(0, str(ROOT))

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.config import CONF

from app.version import UPDATER_PROTOCOL

APP_NAME = "wplace-auto-painter"
UPDATER_NAME = "wplace-auto-painter-updater"
ENTRYPOINT = ROOT / "main.py"
ASSETS = ROOT / "app" / "assets"
ICON = ASSETS / "icon" / "gui.ico"
GENERATED_DIR = ROOT / "build" / "generated"
BUILD_INFO_FILE = GENERATED_DIR / "build_info.json"
UPDATER_FILE = Path(
    os.getenv(
        "UPDATE_HELPER_PATH",
        ROOT / "dist" / f"{UPDATER_NAME}{'.exe' if sys.platform == 'win32' else ''}",
    )
)


def read_project_version() -> str:
    with ROOT.joinpath("pyproject.toml").open("rb") as file:
        version = tomllib.load(file)["project"]["version"]
    if not isinstance(version, str) or not version:
        raise RuntimeError("Invalid project version")
    return version


def read_commit_hash() -> str:
    commit = os.getenv("BUILD_COMMIT")
    if commit is None:
        git = shutil.which("git")
        if git is None:
            raise RuntimeError("Git is not available")
        process = subprocess.run(  # noqa: S603
            [git, "rev-parse", "HEAD"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        commit = process.stdout.strip()
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit.lower()):
        raise RuntimeError("Invalid build commit hash")
    return commit.lower()


def write_build_info() -> dict[str, object]:
    version = read_project_version()
    tag = os.getenv("BUILD_TAG", f"v{version}")
    if tag != f"v{version}":
        raise RuntimeError(f"Build tag {tag!r} does not match project version {version!r}")

    build_info: dict[str, object] = {
        "version": version,
        "tag": tag,
        "commit": read_commit_hash(),
        "updater_protocol": UPDATER_PROTOCOL,
    }
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    BUILD_INFO_FILE.write_text(json.dumps(build_info, indent=2) + "\n", encoding="utf-8")
    return build_info


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


build_info = write_build_info()
if not UPDATER_FILE.is_file():
    raise RuntimeError(f"Update helper is not available: {UPDATER_FILE}")

print("Building main application in one-folder mode")
with ignore_env_path():
    analysis = Analysis(
        scripts=[ENTRYPOINT],
        pathex=[ROOT],
        binaries=[],
        datas=[
            (ASSETS, ASSETS.relative_to(ROOT)),
            (BUILD_INFO_FILE, "app/assets"),
            (UPDATER_FILE, "app/assets/updater"),
        ],
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
    [],
    exclude_binaries=True,
    name=APP_NAME,
    icon=ICON,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=["python3.dll"],
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    contents_directory="_internal",
)
collection = COLLECT(
    executable,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=True,
    upx_exclude=["python3.dll"],
    name=APP_NAME,
)

bundle_dir = Path(str(CONF["distpath"])) / APP_NAME
package_manifest = build_info | {
    "schema_version": 1,
    "executable": f"{APP_NAME}{'.exe' if sys.platform == 'win32' else ''}",
    "managed_entries": [
        f"{APP_NAME}{'.exe' if sys.platform == 'win32' else ''}",
        "_internal",
        "package-manifest.json",
    ],
}
bundle_dir.joinpath("package-manifest.json").write_text(
    json.dumps(package_manifest, indent=2) + "\n",
    encoding="utf-8",
)
