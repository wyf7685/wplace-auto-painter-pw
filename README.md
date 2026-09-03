# wplace-auto-painter-pw

> [!CAUTION]
>
> This project is not affiliated with [WPlace.live](https://wplace.live/), and its use may violate the site's rules. The developers are not responsible for any account penalties. Use at your own risk.

[![python](https://img.shields.io/badge/python-3.14+-blue?logo=python&logoColor=edb641)](https://www.python.org/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
![works on my machine](https://img.shields.io/badge/works%20on-my%20machine-green)

Paint on wplace with playwright

## Download

Download the release archive for your platform from [GitHub Releases](https://github.com/wyf7685/wplace-auto-painter-pw/releases) and extract the entire archive. The application uses a PyInstaller `onedir` layout, so copying only the main executable is not supported.

When migrating from the legacy single-file build, extract the new release into the directory containing the old executable. Release archives do not contain `data/` or `logs/`, so existing configuration, templates, and Playwright browser data are preserved. After this one-time manual migration, future releases can be checked, downloaded, and installed from the Update card on the GUI About page.

## Develop

Before setting up this project, ensure you have the following installed:

- **uv** - A fast Python package installer. See [`astral-sh/uv`](https://github.com/astral-sh/uv)
- **Python 3.14+** - Download from [python.org](https://www.python.org/downloads/) or using `uv`: `uv python install 3.14`

1. Clone the repository:

```bash
git clone https://github.com/wyf7685/wplace-auto-painter-pw.git
cd wplace-auto-painter-pw
```

2. Install dependencies:

```bash
uv sync
uv run prek install
```

3. Run the app:

```bash
uv run main.py
```

## Local Packaging

Build the standalone updater before building the main application. Do not set `BUILD_CI=true` for local builds: `build.spec` and `updater.spec` isolate the build from DLLs that may be introduced through the local `PATH`.

```bash
uv run pyinstaller --clean --noconfirm updater.spec
uv run pyinstaller --clean --noconfirm build.spec
uv run python scripts/release.py package --bundle-dir dist/wplace-auto-painter --platform windows-x86_64 --output-dir release
```

For Linux builds, use `linux-x86_64` as the `--platform` value.

## Releases

The version in `pyproject.toml` is the single source of truth. A release is triggered by a matching SemVer tag. CI validates the tag, builds the Windows and Linux `onedir` archives, generates the SHA-256 update manifest, and publishes the GitHub Release only after every asset has been uploaded successfully.

```bash
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

The tag without its leading `v` must exactly match `[project].version`, and the tagged commit must be reachable from `master`.

## See Also

- [samuelscheit/wplace-archive](https://github.com/samuelscheit/wplace-archive): Awesome archive of wplace
- [aihaisi/wplace-auto-painter](https://github.com/aihaisi/wplace-auto-painter): Paint on wplace with opencv. Inspired this project.
