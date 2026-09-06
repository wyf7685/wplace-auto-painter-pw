import hashlib
import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
import uuid
import zipfile
from collections.abc import Callable
from pathlib import Path, PurePosixPath

from app.config import Config
from app.const import APP_NAME, INSTALL_DIR, IS_FROZEN, PACKAGE_MANIFEST_FILE, UPDATES_DIR, assets
from app.utils.func import subprocess_options
from app.version import UNKNOWN_VERSION, get_build_info

from .client import ReleaseClient
from .model import PackageManifest, PreparedUpdate, UpdateError, UpdateInfo, expected_executable_name

ProgressCallback = Callable[[int, int], None]
CHUNK_SIZE = 1024 * 1024
MAX_UNPACKED_SIZE = 2 * 1024 * 1024 * 1024
MAX_EXPANSION_RATIO = 12


def _proxy_from_config() -> str | None:
    try:
        return Config.load().proxy
    except Exception:
        return None


def _safe_member_path(root: Path, member_name: str) -> Path:
    if "\\" in member_name:
        raise UpdateError(f"Archive member uses an invalid separator: {member_name!r}")

    member = PurePosixPath(member_name)
    if member.is_absolute() or not member.parts or any(part in {"", ".", ".."} for part in member.parts):
        raise UpdateError(f"Unsafe archive member: {member_name!r}")

    target = root.joinpath(*member.parts).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError as exc:
        raise UpdateError(f"Archive member escapes staging directory: {member_name!r}") from exc
    return target


def _validate_unpacked_size(total: int, archive_size: int) -> None:
    maximum = min(MAX_UNPACKED_SIZE, archive_size * MAX_EXPANSION_RATIO)
    if total > maximum:
        raise UpdateError(f"Archive expands beyond the allowed size: {total} > {maximum}")


def _extract_zip(archive: Path, destination: Path, archive_size: int) -> None:
    with zipfile.ZipFile(archive) as file:
        infos = file.infolist()
        _validate_unpacked_size(sum(info.file_size for info in infos), archive_size)
        for info in infos:
            target = _safe_member_path(destination, info.filename)
            mode = info.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise UpdateError(f"Archive contains a symbolic link: {info.filename}")
            if info.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue

            target.parent.mkdir(parents=True, exist_ok=True)
            with file.open(info) as source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            if mode and os.name != "nt":
                target.chmod(mode & 0o777)


def _extract_tar(archive: Path, destination: Path, archive_size: int) -> None:
    with tarfile.open(archive, "r:gz") as file:
        members = file.getmembers()
        _validate_unpacked_size(sum(member.size for member in members), archive_size)
        for member in members:
            target = _safe_member_path(destination, member.name)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            if not member.isfile():
                raise UpdateError(f"Archive contains a non-file entry: {member.name}")

            source = file.extractfile(member)
            if source is None:
                raise UpdateError(f"Cannot read archive member: {member.name}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with source, target.open("wb") as output:
                shutil.copyfileobj(source, output)
            if os.name != "nt":
                target.chmod(member.mode & 0o777)


def _extract_archive(archive: Path, destination: Path, archive_size: int) -> None:
    if archive.name.endswith(".zip"):
        _extract_zip(archive, destination, archive_size)
    elif archive.name.endswith(".tar.gz"):
        _extract_tar(archive, destination, archive_size)
    else:
        raise UpdateError(f"Unsupported update archive: {archive.name}")


def load_package_manifest(path: Path) -> PackageManifest:
    try:
        return PackageManifest.model_validate_json(path.read_bytes())
    except Exception as exc:
        raise UpdateError(f"Invalid package manifest: {path}") from exc


class UpdateService:
    def __init__(self) -> None:
        self._client = ReleaseClient(proxy=_proxy_from_config())

    def check(self) -> UpdateInfo | None:
        local = get_build_info()
        if local is None or local.version == UNKNOWN_VERSION:
            raise UpdateError("Local build metadata is unavailable")
        return self._client.check(local)

    def prepare(self, info: UpdateInfo, progress: ProgressCallback) -> PreparedUpdate:
        if not IS_FROZEN:
            raise UpdateError("Self-update is only available in a packaged application")

        UPDATES_DIR.mkdir(parents=True, exist_ok=True)
        required_space = info.asset.size * 5
        if shutil.disk_usage(UPDATES_DIR).free < required_space:
            raise UpdateError(f"Not enough free space to stage update; need at least {required_space} bytes")

        update_root = UPDATES_DIR / f"{info.manifest.version}-{uuid.uuid4().hex}"
        archive_path = update_root / info.asset.name
        staging_root = update_root / "staging"
        update_root.mkdir(parents=True)

        digest = hashlib.sha256()
        downloaded = 0
        try:
            with (
                self._client.stream_download(info) as response,
                archive_path.with_suffix(f"{archive_path.suffix}.part").open("wb") as output,
            ):
                partial_path = Path(output.name)
                for chunk in response.iter_raw(CHUNK_SIZE):
                    downloaded += len(chunk)
                    if downloaded > info.asset.size:
                        raise UpdateError("Downloaded update is larger than the release manifest")
                    output.write(chunk)
                    digest.update(chunk)
                    progress(downloaded, info.asset.size)
                output.flush()
                os.fsync(output.fileno())

            if downloaded != info.asset.size:
                raise UpdateError(f"Downloaded update size mismatch: {downloaded} != {info.asset.size}")
            if digest.hexdigest() != info.asset.sha256:
                raise UpdateError("Downloaded update checksum mismatch")
            partial_path.replace(archive_path)

            staging_root.mkdir()
            _extract_archive(archive_path, staging_root, info.asset.size)
            payload_dir = staging_root / APP_NAME
            package_manifest = load_package_manifest(payload_dir / "package-manifest.json")
            self._validate_package(info, payload_dir, package_manifest)
        except Exception:
            shutil.rmtree(update_root, ignore_errors=True)
            raise

        return PreparedUpdate(info, archive_path, payload_dir, package_manifest)

    @staticmethod
    def _validate_package(info: UpdateInfo, payload_dir: Path, package: PackageManifest) -> None:
        if package.version != info.manifest.version or package.tag != info.manifest.tag:
            raise UpdateError("Package version does not match update manifest")
        if package.commit != info.manifest.commit:
            raise UpdateError("Package commit does not match update manifest")
        if package.updater_protocol != info.manifest.updater_protocol:
            raise UpdateError("Package updater protocol does not match update manifest")
        if package.executable != expected_executable_name():
            raise UpdateError(f"Unexpected package executable: {package.executable}")
        for entry in package.managed_entries:
            if not (payload_dir / entry).exists():
                raise UpdateError(f"Package managed entry is missing: {entry}")

    def launch_helper(self, prepared: PreparedUpdate, *, headless: bool = False) -> subprocess.Popen[bytes]:
        if not IS_FROZEN:
            raise UpdateError("Self-update is only available in a packaged application")
        if not assets.update_helper.is_file():
            raise UpdateError(f"Update helper is missing: {assets.update_helper}")

        current_package = load_package_manifest(PACKAGE_MANIFEST_FILE)
        self._check_install_writable()

        update_root = prepared.payload_dir.parent.parent
        helper_suffix = ".exe" if os.name == "nt" else ""
        helper_path = UPDATES_DIR / f"helper-{uuid.uuid4().hex}{helper_suffix}"
        shutil.copy2(assets.update_helper, helper_path)
        if os.name != "nt":
            helper_path.chmod(0o755)

        ready_file = update_root / "ready"
        plan_file = update_root / "update-plan.json"
        backup_dir = update_root / "backup"
        log_file = UPDATES_DIR / "updater.log"
        plan = {
            "schema_version": 1,
            "parent_pid": os.getpid(),
            "install_dir": str(INSTALL_DIR),
            "staging_dir": str(prepared.payload_dir),
            "backup_dir": str(backup_dir),
            "executable": prepared.package_manifest.executable,
            "ready_file": str(ready_file),
            "log_file": str(log_file),
            "old_managed_entries": current_package.managed_entries,
            "new_managed_entries": prepared.package_manifest.managed_entries,
            "readiness_timeout": 45.0,
            "headless": headless,
        }
        plan_file.write_text(json.dumps(plan, indent=2), encoding="utf-8")

        try:
            return subprocess.Popen(  # noqa: S603
                [str(helper_path), str(plan_file)],
                cwd=INSTALL_DIR,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                **subprocess_options(),
            )
        except Exception:
            plan_file.unlink(missing_ok=True)
            helper_path.unlink(missing_ok=True)
            raise

    @staticmethod
    def _check_install_writable() -> None:
        try:
            with tempfile.NamedTemporaryFile(dir=INSTALL_DIR, prefix=".update-write-test-", delete=True):
                pass
        except OSError as exc:
            raise UpdateError(f"Application directory is not writable: {INSTALL_DIR}") from exc

    @staticmethod
    def cleanup_old_helpers() -> None:
        if not UPDATES_DIR.is_dir():
            return
        for path in UPDATES_DIR.glob("helper-*"):
            try:
                path.unlink()
            except OSError:
                continue
