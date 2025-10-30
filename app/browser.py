from typing import TYPE_CHECKING

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


async def get_browser(*, headless: bool = False) -> Browser:
    pw = await _get_playwright()
    name = display = Config.load().browser
    channel = None
    if name in ("chrome", "msedge"):
        name, channel = "chromium", name
        display = f"{name} ({channel})"
    browser_type: BrowserType = getattr(pw, name)
    logger.opt(colors=True).debug(f"Launching {'headless ' if headless else ''}browser: <g>{display}</>")
    return await browser_type.launch(channel=channel, headless=headless)


async def shutdown_playwright() -> None:
    global _PLAYWRIGHT
    if _PLAYWRIGHT is not None:
        await _PLAYWRIGHT.stop()
        _PLAYWRIGHT = None
