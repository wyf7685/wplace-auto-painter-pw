# wplace-auto-painter-pw

[![python](https://img.shields.io/badge/python-3.14+-blue?logo=python&logoColor=edb641)](https://www.python.org/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
![works on my machine](https://img.shields.io/badge/works%20on-my%20machine-green)

Paint on wplace with playwright

## Setup

1. Clone the repository:

```bash
git clone https://github.com/wyf7685/wplace-auto-painter-pw.git
cd wplace-auto-painter-pw
```

2. Install dependencies:

> [!note]
>
> Install [`uv`](https://github.com/astral-sh/uv) first if you don't have it

```bash
uv sync
```

## Configuration

Execute the following command to open the config GUI:

```bash
uv run gui_main.py
```

This will create `data/config.json` and `data/templates/` to store your credentials and templates.

## Usage

Simply run:

```bash
uv run main.py
```

Note that if your configuration is not set up or broken, it will open the config GUI first.

> [!note]
>
> Prebuilt binaries are available on [GitHub Actions](https://github.com/wyf7685/wplace-auto-painter-pw/actions) for Windows and Linux.
>
> Note that prebuilt versions have limited support. Running from source is recommended for better compatibility.

## See Also

- [samuelscheit/wplace-archive](https://github.com/samuelscheit/wplace-archive): Awesome archive of wplace
- [aihaisi/wplace-auto-painter](https://github.com/aihaisi/wplace-auto-painter): Paint on wplace with opencv. Inspired this project.
