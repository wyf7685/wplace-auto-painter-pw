from playwright.async_api import Browser, BrowserType, Playwright, async_playwright

from .config import Config
from .log import logger

_PLAYWRIGHT: Playwright | None = None
_BROWSER: Browser | None = None
_BROWSER_HEADLESS: Browser | None = None


async def get_playwright() -> Playwright:
    global _PLAYWRIGHT
    if _PLAYWRIGHT is None:
        logger.debug("Launching Playwright...")
        _PLAYWRIGHT = await async_playwright().start()
    return _PLAYWRIGHT


async def _browser_type() -> BrowserType:
    pw = await get_playwright()
    return getattr(pw, Config.load().browser)


async def get_browser(*, headless: bool = False) -> Browser:
    global _BROWSER, _BROWSER_HEADLESS
    if not headless:
        if _BROWSER is None:
            browser_type = await _browser_type()
            logger.opt(colors=True).debug(f"Launching browser: <g>{Config.load().browser}</>")
            _BROWSER = await browser_type.launch(headless=False)
        return _BROWSER

    if _BROWSER_HEADLESS is None:
        browser_type = await _browser_type()
        logger.opt(colors=True).debug(f"Launching headless browser: <g>{Config.load().browser}</>")
        _BROWSER_HEADLESS = await browser_type.launch(headless=True)

    return _BROWSER_HEADLESS


async def shutdown_playwright() -> None:
    global _BROWSER, _BROWSER_HEADLESS, _PLAYWRIGHT
    if _BROWSER is not None:
        await _BROWSER.close()
        _BROWSER = None
    if _BROWSER_HEADLESS is not None:
        await _BROWSER_HEADLESS.close()
        _BROWSER_HEADLESS = None
    if _PLAYWRIGHT is not None:
        await _PLAYWRIGHT.stop()
        _PLAYWRIGHT = None
