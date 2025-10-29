from playwright.async_api import Browser, BrowserType, Playwright, async_playwright

from app.config import Config
from app.log import logger

_PLAYWRIGHT: Playwright | None = None


async def get_playwright() -> Playwright:
    global _PLAYWRIGHT
    if _PLAYWRIGHT is None:
        logger.debug("Launching Playwright...")
        _PLAYWRIGHT = await async_playwright().start()
    return _PLAYWRIGHT


async def _browser_type() -> tuple[BrowserType, str, str | None]:
    pw = await get_playwright()
    name = Config.load().browser
    channel = None
    if name in ("chrome", "msedge"):
        channel = name
        name = "chromium"

    return getattr(pw, name), name if channel is None else f"{name} ({channel})", channel


async def get_browser(*, headless: bool = False) -> Browser:
    browser_type, name, channel = await _browser_type()
    logger.opt(colors=True).debug(f"Launching {'headless ' if headless else ''}browser: <g>{name}</>")
    return await browser_type.launch(channel=channel, headless=headless)


async def shutdown_playwright() -> None:
    global _PLAYWRIGHT
    if _PLAYWRIGHT is not None:
        await _PLAYWRIGHT.stop()
        _PLAYWRIGHT = None
