# wplace-auto-painter-pw

> [!CAUTION]
>
> This project is not affiliated with [WPlace.live](https://wplace.live/), and its use may violate the site's rules. The developers are not responsible for any account penalties. Use at your own risk.

[![python](https://img.shields.io/badge/python-3.14+-blue?logo=python&logoColor=edb641)](https://www.python.org/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
![works on my machine](https://img.shields.io/badge/works%20on-my%20machine-green)

Paint on wplace with playwright

## 获取应用

从 [GitHub Releases](https://github.com/wyf7685/wplace-auto-painter-pw/releases) 下载对应平台的发布包并完整解压。应用使用 `onedir` 目录结构，不能只复制主程序文件。

首次从旧版单文件程序迁移时，将新发布包内容解压到旧程序所在目录；发布包不包含 `data/` 和 `logs/`，现有配置、模板和 Playwright 浏览器数据会保留。完成这次手动迁移后，可在 GUI 的“关于”页面检查、下载并重启更新。

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

## 本地打包

必须先构建独立 updater，再构建主程序。开发机打包不要设置 `BUILD_CI=true`，`build.spec` 和 `updater.spec` 会隔离本机 `PATH` 中可能污染构建的 DLL。

```bash
uv run pyinstaller --clean --noconfirm updater.spec
uv run pyinstaller --clean --noconfirm build.spec
uv run python scripts/release.py package --bundle-dir dist/wplace-auto-painter --platform windows-x86_64 --output-dir release
```

Linux 打包时将 `--platform` 改为 `linux-x86_64`。

## 版本发布

`pyproject.toml` 中的版本号是唯一版本来源。正式发布使用匹配的 SemVer tag；CI 会验证 tag、构建 Windows/Linux `onedir` 包、生成 SHA-256 更新清单，并在所有资产上传成功后发布 GitHub Release。

```bash
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

tag 去掉前缀 `v` 后必须与 `[project].version` 完全一致，并且 tag 所指向的提交必须位于 `master`。

## See Also

- [samuelscheit/wplace-archive](https://github.com/samuelscheit/wplace-archive): Awesome archive of wplace
- [aihaisi/wplace-auto-painter](https://github.com/aihaisi/wplace-auto-painter): Paint on wplace with opencv. Inspired this project.
