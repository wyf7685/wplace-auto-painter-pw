from playwright.async_api import Browser, BrowserType, Playwright, async_playwright

from .config import config
from .log import logger

_PLAYWRIGHT: Playwright | None = None
_BROWSER: Browser | None = None


async def get_playwright() -> Playwright:
    global _PLAYWRIGHT
    if _PLAYWRIGHT is None:
        _PLAYWRIGHT = await async_playwright().start()
    return _PLAYWRIGHT


async def get_browser() -> Browser:
    global _BROWSER
    if _BROWSER is None:
        pw = await get_playwright()
        browser_type: BrowserType = getattr(pw, config.browser)
        logger.opt(colors=True).info(f"Launching browser: <g>{config.browser}</>")
        _BROWSER = await browser_type.launch(headless=False)
    return _BROWSER


async def shutdown_playwright() -> None:
    global _BROWSER, _PLAYWRIGHT
    if _BROWSER is not None:
        await _BROWSER.close()
        _BROWSER = None
    if _PLAYWRIGHT is not None:
        await _PLAYWRIGHT.stop()
        _PLAYWRIGHT = None
