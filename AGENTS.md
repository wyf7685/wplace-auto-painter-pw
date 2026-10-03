# AGENTS.md

## Project and Scope

Python 3.14 application using Playwright, AnyIO, Pydantic v2, PySide6, and [`bot7685-ext`](https://github.com/wyf7685/bot7685-ext). Preserve existing module boundaries and avoid unrelated refactoring.

- `main.py`, `app/__main__.py`: CLI, startup order, and GUI/headless dispatch.
- `app/wplace/`: painting, template diffs, purchases, and page automation; `paint_input/`: painting input modes.
- `app/browser/`: proxies, persistent contexts, Playwright lifecycle, and idle shutdown.
- `app/gui/`: Qt lifecycle, configuration drafts, runtime state, and update UI.
- `app/config.py`, `app/schemas/`: cached configuration and data models; `app/assets/`: injected scripts and bilingual resources.
- `app/update/`, `app/update_helper.py`, `app/version.py`: update validation, activation, rollback, and version protocols.
- `scripts/release.py`, `build.spec`, `updater.spec`: releases and packaging; `tests/`: permanent tests.

WPlace DOM, minified JavaScript, APIs, coordinate projection, timing, and anti-bot behavior are external contracts. Changes require focused tests or concrete smoke evidence. Never paint or purchase with real accounts unless explicitly requested by the user.

## Commands

Run from the repository root. Use `uv`; the project is not installed as a Python package.

```bash
uv sync
uv run prek install
uv run main.py
uv run main.py --no-gui
uv run main.py --version
uv run poe lint
uv run poe test
uv run poe check
uv run poe build
uv run poe release package --bundle-dir dist/wplace-auto-painter --platform windows-x86_64 --output-dir release
```

- `check` runs lint and tests; `build` runs checks, builds the standalone updater, then builds the onedir application.
- The Linux platform is `linux-x86_64`; Linux Qt tests require `libegl1`. CI uses `uv sync --frozen`.
- Never set `BUILD_CI=true` locally: the spec files isolate analysis from DLLs on the local `PATH`.
- Run `uv run ruff check --fix .` or `uv run ruff format .` only when applying fixes; avoid unrelated formatting.

## Code and Data Conventions

- Ruff: 120 columns, double quotes, spaces, and LF. Add precise type annotations; `ty` checks all platforms, so isolate platform-specific imports.
- Keep identifiers, comments, docstrings, and source text in English. Use `tr()` for GUI text and synchronize keys in `zh_CN` and `en_US`.
- Keep `README.md` and `AGENTS.md` in English. Update `README.md` only when the user explicitly requests it; routine code or documentation synchronization does not authorize README changes.
- Use `pathlib.Path` for filesystem operations and Pydantic v2 for persisted or external structured data. Reuse existing models, exceptions, and lifecycle helpers.
- Use `app.log.logger` / `logger_wrapper` for application logs. Preserve tracebacks and useful context, escape untrusted Loguru markup, and never expose credentials. Preserve configuration `hide_input_in_errors=True` and logging `diagnose=False`.
- Preserve lazy imports that protect startup order and first-paint performance. `--version` must not initialize the GUI or runtime services; keep expensive work off the Qt main thread.
- `data/`, `logs/`, `.local/`, caches, `build/`, `dist/`, and `release/` are runtime or generated data. Never commit credentials, browser profiles, templates, downloaded chunks, or staged updates. Preserve local user data and unrelated changes.
- `data/.config.schema.json` is generated from `Config`; edit the model instead. Update `uv.lock` only when dependency metadata changes, together with `pyproject.toml`.
- Permanent tests belong in `tests/`; root `test*.py` files are ignored scratch scripts. Do not reformat minified injected JavaScript.

## Runtime Contracts

### Concurrency and Painting

- Prefer AnyIO for orchestration. Use raw `asyncio` only for Playwright callbacks, loop identity, and primitives that must be loop-bound.
- Browsers, contexts, pages, task groups, and background operations need explicit owners and cleanup paths. Shield required asynchronous cleanup against cancellation.
- Use the public context managers in `app/browser/manager.py` to preserve per-event-loop Playwright ownership, usage counting, and idle shutdown.
- `setup_paint()` runs one painter per user with staggered starts. A fresh browser context paints a small first batch to absorb the initial Cloudflare challenge. A single-user failure must neither stop other users nor directly mark the entire GUI runtime as failed.
- `CLAIMED_COLORS` acquisition must be atomic and non-blocking; release claims on success, error, and cancellation. Invalidate cached user info after painting or purchasing.
- Preserve selected-area fallback and minimum retry delays; no-op or blocked cycles must not busy-spin.
- Keep `paint_input_mode` models, GUI drafts/options, dispatch, translations, and tests synchronized. Retracing paths may revisit pixels, but charge accounting and submission use the original target pixels.
- `CANVAS_ZOOM` and `CANVAS_PX_PER_PIXEL` are one calibrated contract. Re-measure against the live site if either changes.
- Keep `Painter.paint_pixels` script data, `app/assets/js/paint_btn.js`, and `WplacePage` console topics synchronized. Batch completion requires `submit-success`, not merely successful individual responses.
- Preserve distinct handling for expired tokens, policy blocks, challenges, verification, account timeouts, and generic failures. Purchases run inside the browser context without an explicit `Content-Type` header (see `tests/test_purchase.py`).
- The resolver inspects unstable minified bundles; never assume symbol names are stable.

### Templates, Configuration, and GUI

- Template image processing uses the `bot7685-ext` byte interfaces. Selected areas are `(x, y, width, height)`, clipped to template bounds, and rejected when there is no overlap. Painting coordinates, diff pixels, and previews must use the same crop.
- WPlace coordinate endpoints are inclusive: the final coordinate is the origin offset by `(width - 1, height - 1)`. `WplacePixelCoords` is immutable; construct new coordinates through methods such as `offset()`.
- `Config.load()` is cached. Save through `Config.save()` to synchronize configuration, log-level, and proxy caches. Configuration-field changes must update models, GUI drafts/serialization, both locales for visible text, and relevant tests.
- The GUI editor preserves unsaved drafts; painting may start only after successful validation and saving. When exiting or installing an update, cancellation or a failed save must block the operation.
- Qt list and selection changes may emit signals synchronously; preserve model/draft state before mutating widgets. Workers communicate with the GUI through signals and never mutate widgets directly.

### Updates and Releases

- Release/package version, tag, commit, platform, executable, and updater protocol must agree. `pyproject.toml` is the version source; tags must be `v<project-version>` and their commits reachable from `master`.
- Downloads require exact size and SHA-256 verification. Extraction must reject traversal, absolute paths, invalid separators, links, non-file tar entries, unsupported formats, and excessive expansion.
- Package manifests manage only top-level application entries, never `data` / `logs` or unmanaged entries. Back up before activation and roll back if launch or readiness fails.
- `app/update_helper.py` builds independently and must not import the main application or third-party libraries. Self-update is frozen-build-only. Review `UPDATER_PROTOCOL` for incompatible protocol or schema changes.
- Use `uv run poe release` for releases. `publish-release` requires `gh`, `curl`, and `GH_TOKEN`; it reuses drafts, rejects already-published releases, and publishes only after every asset passes size, SHA-256, and upload-state verification.
- Release archives use an onedir layout and exclude `data/` and `logs/`. Windows builds prune Qt modules and plugins; check the exclusion lists in `build.spec` when introducing Qt features or image formats.

## Verification and Delivery

- For code changes, run the narrowest relevant tests, then `uv run poe check`. For documentation-only changes, verify the corresponding code and commands.
- Keep tests deterministic and isolated from real accounts, credentials, browsers, networks, and GitHub releases. Mock browser, network, and process boundaries.
- Updater changes require success, rollback, and malicious-input coverage in `tests/test_update.py`. GUI changes require actual surface verification; state logic may use offscreen Qt. Packaging changes require both updater and application builds plus a packaged `--version` smoke test.
- Synchronize affected callers, models, GUI, translations, tests, packaging metadata, and documentation, subject to the explicit-request requirement for `README.md`. Use Conventional Commits with a concise Chinese description.
