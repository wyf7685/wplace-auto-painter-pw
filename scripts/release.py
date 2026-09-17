import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import tomllib
import zipfile
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from packaging.version import InvalidVersion, Version

from app.version import UPDATER_PROTOCOL

APP_NAME = "wplace-auto-painter"
PLATFORM_SUFFIXES = {
    "windows-x86_64": ".zip",
    "linux-x86_64": ".tar.gz",
}

UPLOAD_ATTEMPTS = 3
UPLOAD_TIMEOUT_SECONDS = 120
UPLOAD_RETRY_DELAY_SECONDS = 10


@dataclass(frozen=True)
class ReleaseAsset:
    path: Path
    size: int
    digest: str


class ReleaseUploadError(RuntimeError):
    pass


def read_project_version() -> str:
    with ROOT.joinpath("pyproject.toml").open("rb") as file:
        version = tomllib.load(file)["project"]["version"]
    if not isinstance(version, str):
        raise TypeError("Project version must be a string")
    try:
        parsed = Version(version)
    except InvalidVersion as exc:
        raise ValueError(f"Invalid project version: {version}") from exc
    if str(parsed) != version:
        raise ValueError(f"Project version is not normalized: {version}")
    return version


def write_github_output(path: Path | None, **values: str) -> None:
    if path is None:
        return
    with path.open("a", encoding="utf-8") as file:
        for name, value in values.items():
            file.write(f"{name}={value}\n")


def build_info(args: argparse.Namespace) -> None:
    version = read_project_version()
    expected_tag = f"v{version}"
    tag = args.tag or expected_tag
    if tag != expected_tag:
        raise ValueError(f"Tag {tag!r} does not match project version {version!r}")
    write_github_output(args.github_output, version=version, tag=tag)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def run_gh(
    *arguments: str,
    check: bool = True,
    capture_output: bool = False,
    timeout: int | None = None,
) -> subprocess.CompletedProcess[str]:
    executable = shutil.which("gh")
    if executable is None:
        raise RuntimeError("GitHub CLI is unavailable")
    return subprocess.run(  # noqa: S603
        [executable, *arguments],
        check=check,
        capture_output=capture_output,
        text=True,
        timeout=timeout,
    )


def read_release(tag: str) -> dict[str, object] | None:
    process = run_gh(
        "release",
        "view",
        tag,
        "--json",
        "isDraft,assets,uploadUrl",
        check=False,
        capture_output=True,
        timeout=30,
    )
    if process.returncode != 0:
        message = (process.stderr or "").strip()
        if "release not found" in message.lower():
            return None
        raise RuntimeError(f"Unable to inspect release {tag}: {message or 'unknown GitHub CLI error'}")

    release = json.loads(process.stdout)
    if not isinstance(release, dict):
        raise TypeError("GitHub release metadata must be an object")
    return release


def get_release_assets(assets_dir: Path) -> list[ReleaseAsset]:
    version = read_project_version()
    paths = [
        assets_dir / f"{APP_NAME}-v{version}-{platform_key}{suffix}"
        for platform_key, suffix in PLATFORM_SUFFIXES.items()
    ]
    paths.append(assets_dir / "update-manifest.json")

    assets: list[ReleaseAsset] = []
    for path in paths:
        if not path.is_file():
            raise FileNotFoundError(f"Release asset is missing: {path}")
        assets.append(ReleaseAsset(path, path.stat().st_size, f"sha256:{sha256_file(path)}"))
    return assets


def get_remote_release_asset(name: str, release: dict[str, object]) -> dict[str, object] | None:
    remote_assets = release.get("assets")
    if not isinstance(remote_assets, list):
        raise TypeError("GitHub release assets must be a list")
    return next(
        (remote for remote in remote_assets if isinstance(remote, dict) and remote.get("name") == name),
        None,
    )


def release_asset_matches(asset: ReleaseAsset, release: dict[str, object]) -> bool:
    remote = get_remote_release_asset(asset.path.name, release)
    return (
        remote is not None
        and remote.get("size") == asset.size
        and remote.get("digest") == asset.digest
        and remote.get("state") == "uploaded"
    )


def upload_release_asset_data(release: dict[str, object], asset: ReleaseAsset) -> None:
    upload_url = release.get("uploadUrl")
    if not isinstance(upload_url, str) or not upload_url:
        raise TypeError("GitHub release upload URL is unavailable")
    token = os.getenv("GH_TOKEN")
    if not token:
        raise RuntimeError("GH_TOKEN is unavailable")
    executable = shutil.which("curl")
    if executable is None:
        raise RuntimeError("curl is unavailable")

    endpoint = f"{upload_url.partition('{')[0]}?name={quote(asset.path.name, safe='')}"
    process = subprocess.run(  # noqa: S603
        [
            executable,
            "--fail-with-body",
            "--silent",
            "--show-error",
            "--http1.1",
            "--connect-timeout",
            "30",
            "--max-time",
            str(UPLOAD_TIMEOUT_SECONDS),
            "--request",
            "POST",
            "--header",
            "Accept: application/vnd.github+json",
            "--header",
            f"Authorization: Bearer {token}",
            "--header",
            "X-GitHub-Api-Version: 2022-11-28",
            "--header",
            "Content-Type: application/octet-stream",
            "--data-binary",
            f"@{asset.path}",
            endpoint,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=UPLOAD_TIMEOUT_SECONDS + 30,
    )
    if process.returncode != 0:
        message = (process.stderr or process.stdout or "unknown curl error").strip()
        raise ReleaseUploadError(message)


def prepare_draft_release(tag: str) -> None:
    release = read_release(tag)
    if release is None:
        print(f"Creating draft release: {tag}", flush=True)
        run_gh("release", "create", tag, "--draft", "--verify-tag", "--generate-notes", "--title", tag, timeout=30)
        return
    if release.get("isDraft") is not True:
        raise RuntimeError(f"Published release already exists: {tag}")
    print(f"Reusing existing draft release: {tag}", flush=True)


def upload_release_asset(tag: str, asset: ReleaseAsset) -> None:
    for attempt in range(1, UPLOAD_ATTEMPTS + 1):
        release = read_release(tag)
        if release is None:
            raise RuntimeError(f"Draft release disappeared during upload: {tag}")
        if release_asset_matches(asset, release):
            print(f"Release asset already verified: {asset.path.name}", flush=True)
            return

        remote = get_remote_release_asset(asset.path.name, release)
        if remote is not None:
            run_gh("release", "delete-asset", tag, asset.path.name, "--yes", timeout=30)
            release = read_release(tag)
            if release is None:
                raise RuntimeError(f"Draft release disappeared during upload: {tag}")

        print(f"Uploading {asset.path.name} (attempt {attempt}/{UPLOAD_ATTEMPTS})", flush=True)
        try:
            upload_release_asset_data(release, asset)
        except subprocess.TimeoutExpired:
            print(f"Release asset upload timed out: {asset.path.name}", file=sys.stderr, flush=True)
        except ReleaseUploadError as exc:
            print(f"Release asset upload failed: {asset.path.name}: {exc}", file=sys.stderr, flush=True)
        else:
            release = read_release(tag)
            if release is not None and release_asset_matches(asset, release):
                print(f"Release asset uploaded and verified: {asset.path.name}", flush=True)
                return
            print(f"Uploaded asset metadata does not match: {asset.path.name}", file=sys.stderr, flush=True)

        if attempt < UPLOAD_ATTEMPTS:
            time.sleep(attempt * UPLOAD_RETRY_DELAY_SECONDS)

    raise RuntimeError(f"Release asset upload exhausted retries: {asset.path.name}")


def verify_release_assets(tag: str, assets: list[ReleaseAsset]) -> None:
    release = read_release(tag)
    if release is None:
        raise RuntimeError(f"Draft release is missing: {tag}")
    mismatches = [asset.path.name for asset in assets if not release_asset_matches(asset, release)]
    if mismatches:
        raise RuntimeError(f"Release asset verification failed: {', '.join(mismatches)}")
    for asset in assets:
        print(f"Release asset verified: {asset.path.name}", flush=True)


def publish_release(args: argparse.Namespace) -> None:
    version = read_project_version()
    if args.tag != f"v{version}":
        raise ValueError(f"Tag {args.tag!r} does not match project version {version!r}")

    assets = get_release_assets(args.assets_dir)
    prepare_draft_release(args.tag)
    for asset in assets:
        upload_release_asset(args.tag, asset)
    verify_release_assets(args.tag, assets)
    run_gh("release", "edit", args.tag, "--draft=false", "--latest", timeout=30)


def build_manifest(args: argparse.Namespace) -> None:
    version = read_project_version()
    if args.tag != f"v{version}":
        raise ValueError(f"Tag {args.tag!r} does not match project version {version!r}")
    commit = args.commit.lower()
    if len(commit) != 40 or any(char not in "0123456789abcdef" for char in commit):
        raise ValueError("Invalid release commit")

    assets: dict[str, dict[str, object]] = {}
    for platform_key, suffix in PLATFORM_SUFFIXES.items():
        name = f"{APP_NAME}-v{version}-{platform_key}{suffix}"
        path = args.assets_dir / name
        if not path.is_file():
            raise FileNotFoundError(f"Release asset is missing: {path}")
        assets[platform_key] = {
            "name": name,
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }

    manifest = {
        "schema_version": 1,
        "version": version,
        "tag": args.tag,
        "commit": commit,
        "updater_protocol": UPDATER_PROTOCOL,
        "assets": assets,
    }
    args.output.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


def package_asset(args: argparse.Namespace) -> None:
    version = read_project_version()
    suffix = PLATFORM_SUFFIXES.get(args.platform)
    if suffix is None:
        raise ValueError(f"Unsupported release platform: {args.platform}")

    package_manifest_path = args.bundle_dir / "package-manifest.json"
    package_manifest = json.loads(package_manifest_path.read_text("utf-8"))
    if package_manifest.get("version") != version:
        raise ValueError("Package manifest version does not match project version")
    managed_entries = package_manifest.get("managed_entries")
    if not isinstance(managed_entries, list) or not all(isinstance(entry, str) for entry in managed_entries):
        raise TypeError("Package manifest managed_entries must be a string list")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    asset_name = f"{APP_NAME}-v{version}-{args.platform}{suffix}"
    asset_path = args.output_dir / asset_name
    if suffix == ".zip":
        with zipfile.ZipFile(asset_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for entry in managed_entries:
                source = args.bundle_dir / entry
                if source.is_dir():
                    for path in sorted(source.rglob("*")):
                        if path.is_file():
                            archive.write(path, Path(APP_NAME) / path.relative_to(args.bundle_dir))
                elif source.is_file():
                    archive.write(source, Path(APP_NAME) / entry)
                else:
                    raise FileNotFoundError(f"Managed package entry is missing: {source}")
    else:
        with tarfile.open(asset_path, "w:gz") as archive:
            archive.dereference = True
            for entry in managed_entries:
                source = args.bundle_dir / entry
                if not source.exists():
                    raise FileNotFoundError(f"Managed package entry is missing: {source}")
                archive.add(source, arcname=Path(APP_NAME) / entry, recursive=True)

    write_github_output(args.github_output, asset_name=asset_name, asset_path=str(asset_path))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest="command", required=True)

    info_parser = subparsers.add_parser("build-info")
    info_parser.add_argument("--tag", default="")
    info_parser.add_argument("--github-output", type=Path, default=os.getenv("GITHUB_OUTPUT"))
    info_parser.set_defaults(handler=build_info)

    manifest_parser = subparsers.add_parser("build-manifest")
    manifest_parser.add_argument("--assets-dir", type=Path, required=True)
    manifest_parser.add_argument("--tag", required=True)
    manifest_parser.add_argument("--commit", required=True)
    manifest_parser.add_argument("--output", type=Path, required=True)
    manifest_parser.set_defaults(handler=build_manifest)

    package_parser = subparsers.add_parser("package")
    package_parser.add_argument("--bundle-dir", type=Path, required=True)
    package_parser.add_argument("--platform", required=True)
    package_parser.add_argument("--output-dir", type=Path, required=True)
    package_parser.add_argument("--github-output", type=Path, default=os.getenv("GITHUB_OUTPUT"))
    package_parser.set_defaults(handler=package_asset)

    publish_parser = subparsers.add_parser("publish-release")
    publish_parser.add_argument("--assets-dir", type=Path, required=True)
    publish_parser.add_argument("--tag", required=True)
    publish_parser.set_defaults(handler=publish_release)

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.handler(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
