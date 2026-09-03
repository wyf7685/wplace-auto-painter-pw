# AGENTS.md

## Scope and Project

These instructions apply to the entire repository. Preserve existing behavior unless the task explicitly changes it, and prefer small changes within current module boundaries.

WPlace Auto Painter is a Python 3.14 application using Playwright, AnyIO, Pydantic v2, and PySide6. It supports concurrent users, template differencing, charge-aware painting, optional purchases, GUI and development headless modes, and self-updating PyInstaller releases.

WPlace DOM structure, JavaScript bundles, APIs, timing, coordinate projection, and anti-bot behavior are external contracts. Changes touching them require focused tests or concrete smoke evidence. Never run live painting or purchasing against a real account unless the user explicitly requests it.

## Where to Change Code

- `main.py` and `app/__main__.py`: launcher, CLI flags, runtime setup, and GUI/headless dispatch.
- `app/wplace/`: painting orchestration, template diffs, purchases, JavaScript resolution, and page automation.
- `app/browser/`: Playwright installation, proxy settings, persistent contexts, shared lifecycle, and idle shutdown.
- `app/gui/`: Qt lifecycle, configuration UI, translations, logging, painter runtime, and update UI.
- `app/config.py` and `app/schemas/`: cached configuration and Pydantic models for internal and external data.
- `app/update/`, `app/update_helper.py`, and `app/version.py`: release validation, staging, activation, rollback, and protocol metadata.
- `app/assets/`: injected JavaScript, icons, and `zh_CN`/`en_US` locale files.
- `scripts/release.py`, `build.spec`, and `updater.spec`: release metadata, archives, and PyInstaller builds.
- `tests/`: permanent pytest tests. Root `test*.py` files are ignored scratch scripts.

## Commands

Run commands from the repository root. The project uses `uv` and is not installed as a package.

```bash
uv sync
uv run prek install

uv run main.py
uv run main.py --no-gui
uv run main.py --version

uv run ruff check .
uv run ruff format --check .
uv run ty check --python-platform all
uv run python -m pytest tests
```

Use `uv run ruff check --fix .` and `uv run ruff format .` only when applying fixes. CI uses `uv sync --frozen`; dependency changes must update both `pyproject.toml` and `uv.lock`.

Build the standalone updater before the onedir application:

```bash
uv run pyinstaller --clean --noconfirm updater.spec
uv run pyinstaller --clean --noconfirm build.spec
uv run python scripts/release.py package --bundle-dir dist/wplace-auto-painter --platform windows-x86_64 --output-dir release
```

Use `linux-x86_64` for the current Linux target. Do not set `BUILD_CI=true` locally; the spec files intentionally isolate analysis from DLLs on the local `PATH`.

## Repository Hygiene

- `data/`, `logs/`, `.local/`, caches, `build/`, `dist/`, and `release/` are runtime or generated state, not source.
- `data/.config.schema.json` is generated from `Config`; edit its Pydantic model instead.
- Never commit credentials, Cloudflare cookies, browser profiles, templates, logs, downloaded WPlace chunks, or staged updates.
- Do not modify `uv.lock` unless dependency metadata changes.
- Preserve unrelated user changes and local runtime data.

## Code Conventions

- Target Python 3.14. Follow Ruff: 120 columns, double quotes, spaces, and LF endings.
- Add precise type annotations. `ty` checks all platforms; isolate platform-specific imports or configure them explicitly.
- Use `pathlib.Path` for filesystem code and Pydantic v2 models for persisted or external structured data.
- Keep identifiers, comments, docstrings, and source text in English. Route user-visible GUI text through `tr()` and add identical keys to both locale files.
- Use `app.log.logger` or `logger_wrapper`, not `print`, in application code. Escape untrusted values inserted into Loguru markup and never log raw secrets.
- Preserve lazy imports that protect startup order, optional platform dependencies, Qt initialization, headless execution, or cycles.
- Reuse existing helpers, models, exceptions, logging, and lifecycle patterns. Do not add compatibility shims or a second convention.
- Avoid unrelated formatting and do not reformat minified injected JavaScript during focused changes.

## Runtime Invariants

### Concurrency and Ownership

- Application orchestration is AnyIO-first. Use raw `asyncio` only for Playwright callbacks, loop identity, or loop-bound primitives already requiring it.
- Every browser, context, page, task group, worker, and background operation needs an explicit owner and cleanup path.
- Preserve cancellation-safe cleanup; shield required async cleanup when cancellation can interrupt it.
- `app/browser/manager.py` stores Playwright state per asyncio event loop. Use its public context managers so usage counting and idle shutdown remain correct.
- Qt workers communicate through signals and must not mutate widgets directly.

### Painting and Browser Automation

- `setup_paint()` intentionally runs one painter per user with staggered starts. A fresh browser context intentionally paints a small first batch to absorb an initial Cloudflare challenge.
- `CLAIMED_COLORS` acquisition is atomic and non-blocking; claims must be released on success, error, and cancellation.
- Invalidate cached user info after painting or purchasing because charges and droplets changed server-side.
- Preserve selected-area fallback and minimum retry delays; no-op or blocked cycles must not busy-spin.
- `CANVAS_ZOOM` and `CANVAS_PX_PER_PIXEL` are one calibrated contract. Re-measure against the live site if either changes.
- Keep `Painter.paint_pixels` script data, `app/assets/js/paint_btn.js`, and `WplacePage` console topics synchronized.
- Batch completion requires `submit-success`, not only successful individual responses. Preserve distinct handling for expired tokens, policy blocks, challenges, verification, account timeouts, and generic failures.
- Purchases intentionally execute inside the browser context without an explicit `Content-Type` header; `tests/test_purchase.py` pins this contract.
- Resolver regular expressions inspect unstable minified bundles. Do not assume symbol names are stable.

### Configuration and GUI

- `Config.load()` is cached. Save through `Config.save()` so the config, log-level, and proxy caches remain synchronized.
- A configuration-field change must update its Pydantic model, GUI draft/editor serialization, both locales when visible, and relevant tests.
- WPlace coordinate endpoints are inclusive; Pillow crop right/bottom bounds are exclusive. Preserve existing `width - 1` and `height - 1` conversions.
- Qt signals may fire synchronously during list and selection mutations. Preserve model state before mutating widgets.
- Keep network, browser, painter, and updater work off the Qt main thread.

### Updater and Releases

Updater code is security-sensitive:

- Release and package version, tag, commit, platform, executable, and updater protocol must agree.
- Accept downloads only after exact size and SHA-256 verification.
- Extraction must reject traversal, absolute paths, invalid separators, links, non-file tar entries, unsupported formats, and excessive expansion.
- Package manifests manage only top-level application entries; never manage `data` or `logs`, and never overwrite unmanaged entries.
- Activation must back up the old package and restore it if launch or readiness fails.
- `app/update_helper.py` is a standalone build: keep it free of main-application and third-party imports.
- Self-update is frozen-build-only. Review `UPDATER_PROTOCOL` deliberately for incompatible schema or protocol changes.

`pyproject.toml` is the version source of truth. Tags must be exactly `v<project-version>` and reachable from `master`. Release archives use an onedir layout and exclude `data/` and `logs/`.

## Verification and Completion

- Run the narrowest relevant tests first, then the applicable Ruff, format, type, and test commands above.
- Keep tests deterministic and isolated from real accounts, credentials, browsers, GitHub releases, and network access unless an integration check is explicitly required.
- Mock browser, network, and process boundaries while testing repository-owned validation and policy logic.
- Updater changes require success, rollback, and malicious-input coverage in `tests/test_update.py`.
- GUI changes require behavioral verification of the actual surface when possible; use offscreen Qt tests for deterministic state logic.
- Packaging changes require both builds and an executable `--version` smoke test.
- Synchronize affected callers, models, GUI surfaces, translations, tests, packaging metadata, and documentation before completion.

Use Conventional Commits with a concise Chinese description after the type and optional scope.
