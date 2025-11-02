import contextlib
import functools
import re
from collections.abc import AsyncGenerator
from typing import TYPE_CHECKING

from playwright.async_api import ProxySettings

from app.config import Config
from app.log import logger

if TYPE_CHECKING:
    from playwright.async_api import Browser, BrowserType, Playwright

_PLAYWRIGHT: Playwright | None = None


async def _get_playwright() -> Playwright:
    global _PLAYWRIGHT
    if _PLAYWRIGHT is None:
        from playwright.async_api import async_playwright

        logger.debug("Launching Playwright...")
        _PLAYWRIGHT = await async_playwright().start()
    return _PLAYWRIGHT


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
    global _PLAYWRIGHT
    if _PLAYWRIGHT is not None:
        await _PLAYWRIGHT.stop()
        _PLAYWRIGHT = None
