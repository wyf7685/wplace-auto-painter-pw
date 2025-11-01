import random
from datetime import UTC, datetime

import anyio
import anyio.to_thread
import cloudscraper
import httpx

from app.assets import assets
from app.browser import get_browser
from app.config import Config, UserConfig
from app.log import escape_tag, logger

# Event ends at Monday, Nov 3 00:00 AM (UTC)
EVENT_END = datetime(2025, 11, 3, tzinfo=UTC)
PUMPKINS_JSON_URL = "https://wplace.samuelscheit.com/tiles/pumpkin.json"
logger = logger.opt(colors=True)


async def fetch_pumpkin_links() -> dict[int, str]:
    async with httpx.AsyncClient() as client:
        resp = await client.get(PUMPKINS_JSON_URL)
        data: dict = resp.raise_for_status().json()

    result: dict[int, str] = {}
    current_hour = datetime.now().hour
    for pid, info in data.items():
        found = datetime.fromisoformat(info["foundAt"])
        if found.hour == current_hour:
            url = f"https://wplace.live/?lat={info['lat']}&lng={info['lng']}&zoom=14"
            result[int(pid)] = url

    return result


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


async def claim_pumpkins(user: UserConfig) -> set[int] | None:
    prefix = f"<lm>{user.identifier}</> | <ly>Pumpkin</> |"

    links = await fetch_pumpkin_links()
    logger.info(f"{prefix} Fetched <y>{len(links)}</> pumpkin links from api")
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

    while True:
        # Wait until around xx:50 to start claiming pumpkins
        delay = max(0, random.uniform(45, 55) - datetime.now().minute)
        logger.info(f"{prefix} Waiting for <y>{delay:.1f}</> minutes until next claim attempt...")
        await anyio.sleep(delay * 60)

        try:
            claimed = await claim_pumpkins(user)
        except Exception:
            logger.opt(colors=True, exception=True).warning(f"{prefix} Failed to claim pumpkins")
            delay = random.uniform(5, 10)
            logger.info(f"{prefix} Waiting for <y>{delay:.1f}</> minutes before retrying...")
            await anyio.sleep(60 * delay)
            continue

        if claimed is None:
            logger.info(f"{prefix} Waiting for the next claim attempt...")
            await anyio.sleep(60 * random.uniform(10, 15))
            continue

        if len(claimed) >= 100:
            logger.success(f"{prefix} Already claimed all pumpkins.")
            return

        logger.info(f"{prefix} Claimed <y>{len(claimed)}</> pumpkins so far.")
        logger.debug(f"{prefix} Claimed pumpkin IDs: {', '.join(f'<g>{i}</>' for i in sorted(claimed))}")
        logger.info(f"{prefix} Waiting for the next claim attempt...")


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
