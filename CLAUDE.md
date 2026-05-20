# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

WPlace Auto Painter — an automated pixel painter for WPlace.live (collaborative pixel art canvas). Uses Playwright to control a browser, painting pixels according to template images. Supports multiple concurrent users, auto-purchase of charges, and both GUI (PySide6) and headless modes.

## Commands

```bash
uv sync                          # Install dependencies
uv run python -m app             # Run with GUI
uv run python -m app --no-gui    # Run headless
uv run ruff check --fix          # Lint (with auto-fix)
uv run ruff format               # Format
uv run pyinstaller build.spec    # Build executable
uv run prek install              # Install pre-commit hooks (ruff + basedpyright)
```

## Architecture

- **Entry point**: `app/__main__.py` — parses `--no-gui` flag, launches GUI controller or runs `run_painter()` directly
- **`app/wplace/`** — Core painting logic
  - `paint.py`: `Painter` class — main loop: diff template vs canvas, paint pixels with randomized delays, sleep until charges regenerate
  - `template.py`: Template diff calculation against current canvas state
  - `resolver.py`: Resolves JS chunk URLs for paint button injection
  - `purchase.py`: Auto-purchase charge logic
- **`app/browser/`** — Playwright browser lifecycle with shared singleton instance, reference counting, and idle auto-shutdown
- **`app/gui/`** — PySide6 + qfluentwidgets Fluent Design UI
  - `runtime.py`: `TaskRuntime` runs async painter in a background thread, communicates via Qt signals
  - `controller.py`: QApplication lifecycle
- **`app/schemas/`** — Pydantic models for config, templates, coordinates, API responses
- **`app/config.py`** — Config loaded from `data/config.json`
- **`app/assets/`** — Icons, injected JS scripts, locale files

## Key Patterns

- **Async-first** via `anyio` (not raw asyncio) — multiple users paint concurrently via task groups
- **Pydantic v2** for all data validation and serialization
- **Config-driven** — runtime config in `data/config.json` with auto-generated JSON Schema
- **JS injection** into browser pages for paint button automation (base64-encoded scripts in assets)
- **i18n** — Chinese (zh_CN) and English (en_US) via `app/gui/i18n.py`

## Code Style

- Python ≥3.14, line length 120, target py314
- Ruff for linting and formatting (see `ruff.toml` for rule set)
- basedpyright for type checking
- Comments and code identifiers in English; explanations in Chinese
- Conventional Commits with Chinese descriptions for commit messages

## Dependencies

Key runtime: `anyio`, `playwright`, `pydantic`, `httpx`, `PySide6`, `pyside6-fluent-widgets`, `pillow`, `loguru`, `bot7685-ext`, `cloudscraper`
