from __future__ import annotations

import platform
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from packaging.version import InvalidVersion, Version
from pydantic import BaseModel, Field, field_validator, model_validator

from app.const import APP_NAME


class UpdateError(Exception):
    """Base error raised by the application updater."""


class UpdateProtocolError(UpdateError):
    """The release requires a newer updater protocol."""


class ReleaseAssetSpec(BaseModel):
    name: str = Field(min_length=1)
    size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("name")
    @classmethod
    def validate_name(cls, name: str) -> str:
        if Path(name).name != name or not name:
            raise ValueError(f"Unsafe release asset name: {name!r}")
        return name


class UpdateManifest(BaseModel):
    schema_version: Literal[1]
    version: str
    tag: str
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    updater_protocol: int = Field(ge=1)
    assets: dict[str, ReleaseAssetSpec]

    @model_validator(mode="after")
    def validate_version_tag(self) -> UpdateManifest:
        try:
            Version(self.version)
        except InvalidVersion as exc:
            raise ValueError(f"Invalid release version: {self.version}") from exc
        if self.tag != f"v{self.version}":
            raise ValueError("Release tag does not match version")
        return self


class PackageManifest(BaseModel):
    schema_version: Literal[1]
    version: str
    tag: str
    commit: str = Field(pattern=r"^[0-9a-f]{40}$")
    updater_protocol: int = Field(ge=1)
    executable: str
    managed_entries: list[str] = Field(min_length=1)

    @field_validator("managed_entries")
    @classmethod
    def validate_managed_entries(cls, entries: list[str]) -> list[str]:
        unique_entries = list(dict.fromkeys(entries))
        for entry in unique_entries:
            if not entry or entry in {".", "..", "data", "logs"} or Path(entry).name != entry:
                raise ValueError(f"Unsafe managed entry: {entry!r}")
        return unique_entries

    @model_validator(mode="after")
    def validate_package(self) -> PackageManifest:
        try:
            Version(self.version)
        except InvalidVersion as exc:
            raise ValueError(f"Invalid package version: {self.version}") from exc
        if self.tag != f"v{self.version}":
            raise ValueError("Package tag does not match version")
        if self.executable not in self.managed_entries:
            raise ValueError("Package executable is not a managed entry")
        return self


class GitHubReleaseAsset(BaseModel):
    name: str
    browser_download_url: str
    size: int = Field(ge=0)
    state: str


class GitHubRelease(BaseModel):
    tag_name: str
    html_url: str
    draft: bool
    prerelease: bool
    assets: list[GitHubReleaseAsset]


@dataclass(frozen=True)
class UpdateInfo:
    manifest: UpdateManifest
    asset: ReleaseAssetSpec
    asset_url: str
    release_url: str


@dataclass(frozen=True)
class PreparedUpdate:
    info: UpdateInfo
    archive_path: Path
    payload_dir: Path
    package_manifest: PackageManifest


def current_platform_key() -> str:
    os_name = {"win32": "windows", "linux": "linux"}.get(sys.platform)
    if os_name is None:
        raise UpdateError(f"Unsupported update platform: {sys.platform}")

    machine = platform.machine().lower()
    architecture = {
        "amd64": "x86_64",
        "x86_64": "x86_64",
        "aarch64": "arm64",
        "arm64": "arm64",
    }.get(machine)
    if architecture is None:
        raise UpdateError(f"Unsupported update architecture: {machine}")
    return f"{os_name}-{architecture}"


def expected_executable_name() -> str:
    return f"{APP_NAME}.exe" if sys.platform == "win32" else APP_NAME
