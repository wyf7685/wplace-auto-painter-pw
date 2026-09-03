import argparse
import hashlib
import json
import os
import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from packaging.version import InvalidVersion, Version

from app.version import UPDATER_PROTOCOL

APP_NAME = "wplace-auto-painter"
PLATFORM_SUFFIXES = {
    "windows-x86_64": ".zip",
    "linux-x86_64": ".tar.gz",
}


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

    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.handler(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
