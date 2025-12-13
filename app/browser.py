import contextlib
import functools
import re
from collections.abc import AsyncGenerator
from datetime import datetime
from typing import TYPE_CHECKING

import anyio

from app.config import Config
from app.log import logger

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserType, Playwright, ProxySettings

PLAYWRIGHT_MAX_IDLE_TIME = 600  # seconds
_playwright: Playwright | None = None
_last_used: datetime | None = None


async def _get_playwright() -> Playwright:
    global _playwright, _last_used
    if _playwright is None:
        from playwright.async_api import async_playwright

        logger.debug("Launching Playwright...")
        _playwright = await async_playwright().start()

    _last_used = datetime.now()
    return _playwright


@functools.cache
def _proxy_settings() -> ProxySettings | None:
    proxy_host = Config.load().proxy
    if not proxy_host:
        return None

    proxy_pattern = re.compile(
        r"^(?P<protocol>https?|socks5?|http)://"
        r"(?P<username>[^:]+):(?P<password>[^@]+)"
        r"@(?P<host>[^:/]+)(?::(?P<port>\d+))?$",
        re.IGNORECASE,
    )

    if match := proxy_pattern.match(proxy_host):
        proxy_info = match.groupdict()
        proxy_url = f"{proxy_info['protocol']}://{proxy_info['host']}:{proxy_info['port'] or 80}"
        return {
            "server": proxy_url,
            "username": proxy_info["username"],
            "password": proxy_info["password"],
        }

    return {"server": proxy_host}


@contextlib.asynccontextmanager
async def get_browser(*, headless: bool = False) -> AsyncGenerator[Browser]:
    pw = await _get_playwright()
    name = display = Config.load().browser
    channel = None
    if name in ("chrome", "msedge"):
        name, channel = "chromium", name
        display = f"{name} ({channel})"
    browser_type: BrowserType = getattr(pw, name)
    logger.opt(colors=True).debug(f"Launching browser <g>{display}</> with <c>headless</>=<y>{headless}</>")
    browser = await browser_type.launch(channel=channel, headless=headless, proxy=_proxy_settings())
    async with browser:
        yield browser


async def shutdown_playwright() -> None:
    global _playwright
    if _playwright is not None:
        logger.debug("Shutting down Playwright...")
        await _playwright.stop()
        _playwright = None


async def shutdown_idle_playwright_loop() -> None:
    while True:
        await anyio.sleep(PLAYWRIGHT_MAX_IDLE_TIME // 4)
        if (
            _playwright is not None
            and _last_used is not None
            and (datetime.now() - _last_used).total_seconds() >= PLAYWRIGHT_MAX_IDLE_TIME
        ):
            logger.debug("Shutting down idle Playwright...")
            await shutdown_playwright()
