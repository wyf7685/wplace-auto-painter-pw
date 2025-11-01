# wplace-auto-painter-pw

[![python](https://img.shields.io/badge/python-3.14+-blue?logo=python&logoColor=edb641)](https://www.python.org/)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
![works on my machine](https://img.shields.io/badge/works%20on-my%20machine-green)

Paints on wplace with playwright

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
uv run main.py config
```

This will create `data/config.json` and `data/templates/` to store your credentials and templates.

## Usage

Simply run:

```bash
uv run main.py
```

Note that if your configuration is not set up or broken, it will open the config GUI first.
