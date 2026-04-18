"""Playwright and Browser lifecycle management.

Architecture
------------
* A single :class:`playwright.async_api.Playwright` instance is shared across
  all ``get_browser()`` calls and is started lazily on first use.
* Each ``get_browser()`` invocation launches a **fresh** browser process and
  closes it when the context exits, matching the original semantics.
* Usage is tracked via ``_in_use``.  When the counter drops to zero the idle
  timer is armed.  If no new browser is requested within
  ``PLAYWRIGHT_IDLE_TIMEOUT`` seconds the Playwright instance is stopped to
  reclaim memory.  It will be restarted transparently on the next call.

Idle shutdown
-------------
1. ``_idle_event`` is set every time ``_in_use`` drops to 0.
2. ``shutdown_idle_playwright_loop`` waits for that event, then sleeps only
   as long as necessary to reach the deadline (``_last_use_ended +
   IDLE_TIMEOUT``).
3. If the browser was used again during the sleep the in-use counter is
   non-zero and/or ``_last_use_ended`` has been updated, so the loop simply
   restarts without shutting down.
"""

import asyncio
import contextlib
import dataclasses
import functools
import re
import time
from pathlib import Path
from typing import TYPE_CHECKING

from app.config import Config
from app.exception import BrowserNotAvailable
from app.log import logger

from .const import PLAYWRIGHT_IDLE_TIMEOUT
from .install import install_playwright_browser, setup_playwright_env

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from playwright.async_api import Browser, BrowserContext, BrowserType, Playwright, ProxySettings, ViewportSize

# ---------------------------------------------------------------------------
# Loop bounded state
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class _PlaywrightState:
    instance: Playwright | None = None
    in_use: int = 0
    last_use_ended: float = 0.0
    instance_lock: asyncio.Lock = dataclasses.field(default_factory=asyncio.Lock)
    idle_event: asyncio.Event = dataclasses.field(default_factory=asyncio.Event)


_pw_states: dict[asyncio.AbstractEventLoop, _PlaywrightState] = {}


def _cleanup_states() -> None:
    """Clean up _PlaywrightState entries for event loops that have been closed."""
    dead_loops = {loop for loop in _pw_states if loop.is_closed()}
    for loop in dead_loops:
        logger.debug(f"Cleaning up Playwright state for dead loop {loop}")
        del _pw_states[loop]


def _get_state() -> _PlaywrightState:
    _cleanup_states()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        raise RuntimeError("Playwright state can only be accessed from an async context") from None

    if loop not in _pw_states:
        _pw_states[loop] = _PlaywrightState()
    return _pw_states[loop]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _ensure_playwright() -> Playwright:
    """Return the shared Playwright instance, starting it (and optionally
    installing the browser) if necessary.  Thread-safe via asyncio Lock."""
    state = _get_state()
    async with state.instance_lock:
        if state.instance is not None:
            return state.instance

        from playwright.async_api import async_playwright

        setup_playwright_env()
        logger.debug("Starting Playwright...")
        pw = await async_playwright().start()

        # Verify the configured browser binary is present by attempting a
        # headless launch.  If it fails, install it and restart.
        browser_name, _ = _resolve_browser_type()
        browser_type: BrowserType = getattr(pw, browser_name)
        try:
            probe = await browser_type.launch(headless=True)
            await probe.close()
            logger.debug(f"Playwright browser {browser_name!r} is available.")
        except Exception as exc:
            logger.warning(f"Browser {browser_name!r} not found\n{exc}")
            logger.warning("Attempting automatic installation...")
            await pw.stop()
            installed = await install_playwright_browser(browser_name)
            if not installed:
                raise BrowserNotAvailable(f"Failed to install Playwright browser: {browser_name!r}") from exc
            pw = await async_playwright().start()
            logger.debug(f"Playwright restarted after installing {browser_name!r}.")

        state.instance = pw
        return pw


def _resolve_browser_type() -> tuple[str, str | None]:
    """Map channel aliases (chrome, msedge) to the underlying engine name."""
    config = Config.load()
    name = config.browser
    channel: str | None = None
    if name in ("chrome", "msedge"):
        name, channel = "chromium", name
    return name, channel


@functools.cache
def _proxy_settings() -> ProxySettings | None:
    proxy_host = Config.load().proxy
    if not proxy_host:
        return None

    pattern = re.compile(
        r"^(?P<protocol>https?|socks5?|http)://"
        r"(?P<username>[^:]+):(?P<password>[^@]+)"
        r"@(?P<host>[^:/]+)(?::(?P<port>\d+))?$",
        re.IGNORECASE,
    )
    if m := pattern.match(proxy_host):
        info = m.groupdict()
        url = f"{info['protocol']}://{info['host']}:{info['port'] or 80}"
        return {"server": url, "username": info["username"], "password": info["password"]}

    return {"server": proxy_host}


async def _get_browser_type() -> tuple[BrowserType, str, str | None]:
    pw = await _ensure_playwright()
    name, channel = _resolve_browser_type()
    return getattr(pw, name), name, channel


@contextlib.asynccontextmanager
async def _hold_browser() -> AsyncGenerator[None]:
    """Context manager that increments the in-use counter for the
    duration of the context.  Used by get_browser() and get_persistent_context()
    to track usage."""
    state = _get_state()
    state.in_use += 1
    try:
        yield
    finally:
        state.in_use -= 1
        state.last_use_ended = time.monotonic()
        if state.in_use == 0:
            state.idle_event.set()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@contextlib.asynccontextmanager
async def get_browser(*, headless: bool = False) -> AsyncGenerator[Browser]:
    """Async context manager that yields a freshly launched :class:`Browser`.

    The Playwright instance is shared and reused; only the browser process is
    created and destroyed per invocation.
    """
    browser_type, name, channel = await _get_browser_type()
    display = f"{name} ({channel})" if channel else name
    logger.opt(colors=True).debug(f"Launching browser <g>{display}</> with <c>headless</>=<y>{headless}</>")

    browser: Browser = await browser_type.launch(
        channel=channel,
        headless=headless,
        proxy=_proxy_settings(),
    )
    async with _hold_browser(), browser:
        yield browser


@contextlib.asynccontextmanager
async def get_persistent_context(
    user_data_dir: Path,
    viewport: ViewportSize | None = None,
) -> AsyncGenerator[BrowserContext]:
    browser_type, name, channel = await _get_browser_type()
    display = f"{name} ({channel})" if channel else name

    user_data_dir = user_data_dir.joinpath(name if not channel else f"{name}_{channel}")
    logger.opt(colors=True).debug(f"Launching persistent context for <g>{display}</> at <i><y>{user_data_dir}</></>")

    context = await browser_type.launch_persistent_context(
        user_data_dir=user_data_dir,
        channel=channel,
        headless=False,
        proxy=_proxy_settings(),
        viewport=viewport,
        java_script_enabled=True,
    )
    async with _hold_browser(), context:
        yield context


async def shutdown_playwright() -> None:
    """Stop the shared Playwright instance.  Safe to call even if not running."""
    state = _get_state()
    async with state.instance_lock:
        if state.instance is None:
            return
        pw, state.instance = state.instance, None

    logger.debug("Shutting down Playwright...")
    with contextlib.suppress(Exception):
        await pw.stop()
    logger.debug("Playwright stopped.")


async def shutdown_idle_playwright_loop() -> None:
    """Background coroutine that stops Playwright after it has been idle for
    ``PLAYWRIGHT_IDLE_TIMEOUT`` seconds.

    Designed to be run as a long-lived task alongside the main work tasks::

        async with anyio.create_task_group() as tg:
            tg.start_soon(setup_paint)
            tg.start_soon(shutdown_idle_playwright_loop)

    **Algorithm** (event-based, no polling):

    1. Block until ``_idle_event`` is set (i.e., ``_in_use`` just dropped to 0).
    2. Clear the event and compute the remaining time until the idle deadline.
    3. Sleep only for that remaining duration.
    4. If ``_in_use`` is still 0 *and* the deadline has truly passed, shut down
       Playwright.  Otherwise restart from step 1.
    """
    logger.debug("Idle Playwright shutdown loop started.")
    state = _get_state()
    while True:
        # Wait until someone signals that there are no active browsers.
        await state.idle_event.wait()
        state.idle_event.clear()

        # Sleep until the idle deadline.  _last_use_ended may advance while we
        # sleep (if the browser is used again and released), which is fine — we
        # will simply find _in_use > 0 or the deadline has not yet passed.
        deadline = state.last_use_ended + PLAYWRIGHT_IDLE_TIMEOUT
        remaining = deadline - time.monotonic()
        if remaining > 0:
            logger.debug(f"Playwright became idle; will shut down in {remaining:.0f}s if no new requests arrive.")
            await asyncio.sleep(remaining)

        # Guard: the browser may have been used again while we were sleeping.
        if state.in_use > 0:
            continue

        # Guard: _last_use_ended may have been updated (another idle cycle
        # started and our sleep did not cover the new deadline).
        if time.monotonic() < state.last_use_ended + PLAYWRIGHT_IDLE_TIMEOUT:
            continue

        if state.instance is not None:
            logger.debug(f"Playwright has been idle for {PLAYWRIGHT_IDLE_TIMEOUT}s; shutting down.")
            await shutdown_playwright()
