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

3. Install browser for playwright:

```bash
# install chromium for playwright
uv run playwright install chromium

# or install firefox
# uv run playwright install firefox

# or install webkit
# uv run playwright install webkit
```

4. Configure your credentials and template in `./data/config.json`.

```jsonc
{
  "template": {
    // Top-left corner pixel coordinates of the template image on wplace
    "coords": {
      "tlx": 12,
      "tly": 34,
      "pxx": 56,
      "pxy": 78
    }
  },
  "credentials": {
    "token": "YOUR_TOKEN",
    "cf_clearance": "YOUR_CF_CLEARANCE" // Use "" if not exists
  },
  // Available: "chromium", "firefox", "webkit", defaults to "chromium"
  // Should match the installed browser
  "browser": "chromium"
}
```

5. Place your template image in `./data/template.png`.

6. Execute the program:

```bash
uv run main.py
```
