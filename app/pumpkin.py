import random
from datetime import UTC, datetime

import anyio
import anyio.to_thread
import cloudscraper

from app.assets import assets
from app.browser import get_browser
from app.config import Config, UserConfig
from app.log import escape_tag, logger

# Event ends at Monday, Nov 3 00:00 AM (UTC)
EVENT_END = datetime(2025, 11, 3, tzinfo=UTC)
SCRIPT = r"""
() => [...document.querySelector('#pumpkins-modal').querySelectorAll('a')].map(e => {
    const text = e.parentElement.children[0].textContent;
    const res = /^(\d+).*Found\s?at\s?(\d+):(\d+)/.exec(text);
    return [res[1], res[2], res[3], e.getAttribute('href')];
})
"""
logger = logger.opt(colors=True)


def fetch_claimed_pumpkins(user: UserConfig) -> set[int]:
    url = "https://backend.wplace.live/event/hallowen/pumpkins/claimed"
    cookies = {"j": user.credentials.token}
    if user.credentials.cf_clearance:
        cookies["cf_clearance"] = user.credentials.cf_clearance

    try:
        resp = cloudscraper.create_scraper().get(url, cookies=cookies)
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"Failed to load claimed pumpkins: {e}") from e

    return set(data["claimed"] or [])


async def claim_pumpkins(user: UserConfig, previous_claimed: set[int] | None) -> set[int] | None:
    prefix = f"<lm>{user.identifier}</> | <ly>Pumpkin</> |"
    previous_claimed = previous_claimed or set()

    async with (
        await get_browser(headless=True) as browser,
        await browser.new_context(viewport={"width": 1280, "height": 720}, java_script_enabled=True) as context,
        await context.new_page() as page,
    ):
        await page.goto("https://wplace.samuelscheit.com/#pumpkins=1")
        await page.wait_for_selector("#pumpkins-modal")
        await page.wait_for_selector("#pumpkins-modal a")
        current_hour = datetime.now().hour
        links = {
            int(pid): url
            for pid, hour, minute, url in await page.evaluate(SCRIPT)
            if int(hour) == current_hour and int(minute) >= 5 and int(pid) not in previous_claimed
        }
        logger.info(f"Resolved <y>{len(links)}</> pumpkin links")
        if not links:
            logger.info(f"{prefix} No pumpkins available at this time.")
            return None

    claimed = await anyio.to_thread.run_sync(fetch_claimed_pumpkins, user)
    if len(claimed) >= 100:
        return claimed
    for pid in claimed:
        links.pop(pid, None)
    if not links:
        logger.info(f"{prefix} No unclaimed pumpkins available at this time.")
        return claimed

    async with (
        await get_browser() as browser,
        await browser.new_context(viewport={"width": 1280, "height": 720}, java_script_enabled=True) as context,
    ):
        await context.add_init_script(assets.page_init())
        await context.add_cookies(user.credentials.to_cookies())

        async with await context.new_page() as page:
            for pid, link in links.items():
                await page.goto(link, wait_until="networkidle")
                if (viewport := page.viewport_size) is None:
                    raise RuntimeError("Failed to get viewport size")
                await page.mouse.click(viewport["width"] // 2, viewport["height"] // 5 * 3)
                try:
                    if claim_button := await page.wait_for_selector('.btn.btn-primary:has-text("Claim")', timeout=3000):
                        await claim_button.click()
                        if await page.wait_for_selector('.btn.btn-primary:has-text("Claimed")', timeout=3000):
                            logger.info(f"{prefix} Claimed pumpkin #<g>{pid}</>")
                except Exception:
                    logger.warning(f"{prefix} Failed to claim pumpkin #<g>{pid}</>")
                await anyio.sleep(random.uniform(3, 6))

    return await anyio.to_thread.run_sync(fetch_claimed_pumpkins, user)


async def pumpkin_claim_loop(user: UserConfig) -> None:
    prefix = f"<lm>{user.identifier}</> | <ly>Pumpkin</> |"
    claimed: set[int] | None = None

    while True:
        # Wait until around xx:50 to start claiming pumpkins
        delay = max(0, random.uniform(45, 55) - datetime.now().minute)
        logger.info(f"{prefix} Waiting for <y>{delay:.1f}</> minutes until next claim attempt...")
        await anyio.sleep(delay * 60)

        try:
            current_claimed = await claim_pumpkins(user, claimed)
        except Exception:
            logger.opt(colors=True, exception=True).warning(f"{prefix} Failed to claim pumpkins")
            delay = random.uniform(5, 10)
            logger.info(f"{prefix} Waiting for <y>{delay:.1f}</> minutes before retrying...")
            await anyio.sleep(60 * delay)
            continue

        if current_claimed is None:
            logger.info(f"{prefix} Waiting for the next claim attempt...")
            await anyio.sleep(60 * random.uniform(10, 15))
            continue

        if len(current_claimed) >= 100:
            logger.success(f"{prefix} Already claimed all pumpkins.")
            return

        logger.info(f"{prefix} Claimed <y>{len(current_claimed)}</> pumpkins so far.")
        logger.info(f"{prefix} Waiting for the next claim attempt...")
        claimed = current_claimed


async def setup_pumpkin_event() -> None:
    now = datetime.now(UTC)
    if now >= EVENT_END:
        logger.info("Pumpkin event has ended.")
        return

    logger.info("Pumpkin event is active.")
    async with anyio.create_task_group() as tg:
        for user in Config.load().users:
            logger.opt(colors=True).info(f"Starting pumpkin claim loop for user: <lm>{escape_tag(user.identifier)}</>")
            tg.start_soon(pumpkin_claim_loop, user)
            await anyio.sleep(30)
