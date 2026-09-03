from __future__ import annotations

import contextlib
from collections.abc import Iterator

import httpx
from packaging.version import InvalidVersion, Version

from app.const import REPOSITORY_API_URL
from app.version import BuildInfo

from .model import GitHubRelease, UpdateError, UpdateInfo, UpdateManifest, UpdateProtocolError, current_platform_key

API_VERSION = "2026-03-10"
MANIFEST_ASSET_NAME = "update-manifest.json"
REQUEST_TIMEOUT = httpx.Timeout(30.0, connect=10.0)


class ReleaseClient:
    def __init__(self, *, proxy: str | None = None) -> None:
        self._proxy = proxy

    def _client(self) -> httpx.Client:
        return httpx.Client(
            proxy=self._proxy,
            follow_redirects=True,
            timeout=REQUEST_TIMEOUT,
            headers={
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": API_VERSION,
                "User-Agent": "wplace-auto-painter-updater",
            },
        )

    def check(self, local: BuildInfo) -> UpdateInfo | None:
        with self._client() as client:
            response = client.get(f"{REPOSITORY_API_URL}/releases/latest")
            response.raise_for_status()
            release = GitHubRelease.model_validate(response.json())
            if release.draft or release.prerelease:
                raise UpdateError("Latest release is not a stable published release")

            manifest_asset = next((asset for asset in release.assets if asset.name == MANIFEST_ASSET_NAME), None)
            if manifest_asset is None or manifest_asset.state != "uploaded":
                raise UpdateError("Release update manifest is missing")

            manifest_response = client.get(manifest_asset.browser_download_url)
            manifest_response.raise_for_status()
            manifest = UpdateManifest.model_validate_json(manifest_response.content)

        if manifest.tag != release.tag_name:
            raise UpdateError("Release tag does not match update manifest")
        if manifest.updater_protocol > local.updater_protocol:
            raise UpdateProtocolError(
                "Release requires updater protocol "
                f"{manifest.updater_protocol}; local protocol is {local.updater_protocol}"
            )

        try:
            if Version(manifest.version) <= Version(local.version):
                return None
        except InvalidVersion as exc:
            raise UpdateError(f"Invalid local version: {local.version}") from exc

        platform_key = current_platform_key()
        asset_spec = manifest.assets.get(platform_key)
        if asset_spec is None:
            raise UpdateError(f"Release does not contain an asset for {platform_key}")

        release_asset = next((asset for asset in release.assets if asset.name == asset_spec.name), None)
        if release_asset is None or release_asset.state != "uploaded":
            raise UpdateError(f"Release asset is missing: {asset_spec.name}")
        if release_asset.size != asset_spec.size:
            raise UpdateError(f"Release asset size does not match manifest: {asset_spec.name}")

        return UpdateInfo(
            manifest=manifest,
            asset=asset_spec,
            asset_url=release_asset.browser_download_url,
            release_url=release.html_url,
        )

    @contextlib.contextmanager
    def stream_download(self, info: UpdateInfo) -> Iterator[httpx.Response]:
        with self._client() as client, client.stream("GET", info.asset_url) as response:
            response.raise_for_status()
            yield response
