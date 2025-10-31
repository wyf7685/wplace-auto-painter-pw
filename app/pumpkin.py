import random
from datetime import UTC, datetime

import anyio

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


async def resolve_pumpkin_links() -> dict[int, str]:
    async with await get_browser(headless=True) as browser, await browser.new_page() as page:
        await page.goto("https://wplace.samuelscheit.com/#pumpkins=1")
        await page.wait_for_selector("#pumpkins-modal")
        await page.wait_for_selector("#pumpkins-modal a")
        links: list[str] = await page.evaluate(SCRIPT)
        h = datetime.now().hour
        result = {int(pid): url for pid, hour, minute, url in links if int(hour) == h and int(minute) >= 10}
        logger.info(f"Resolved <y>{len(result)}</> pumpkin links")
        return result


async def claim_pumpkins(user: UserConfig) -> int:
    prefix = f"<lm>{user.identifier}</> |"
    links = await resolve_pumpkin_links()

    async def fetch_claimed_pumpkins() -> set[int]:
        resp = await page.goto(
            "https://backend.wplace.live/event/hallowen/pumpkins/claimed",
            wait_until="networkidle",
        )
        if resp is None:
            raise RuntimeError("Failed to load claimed pumpkins: No response")
        if not resp.ok:
            raise RuntimeError(f"Failed to load claimed pumpkins: {resp.status}")
        return set((await resp.json())["claimed"])

    async with (
        await get_browser() as browser,
        await browser.new_context(viewport={"width": 1280, "height": 720}, java_script_enabled=True) as context,
    ):
        await context.add_init_script(assets.page_init())
        await context.add_cookies(user.credentials.to_cookies())

        async with await context.new_page() as page:
            for pid in await fetch_claimed_pumpkins():
                links.pop(pid, None)

            logger.info(f"{prefix} Found <y>{len(links)}</> pumpkins to claim")

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
                await anyio.sleep(2)

            return len(await fetch_claimed_pumpkins())


async def pumpkin_claim_loop(user: UserConfig) -> None:
    prefix = f"<lm>{user.identifier}</> |"
    while True:
        await anyio.sleep(max(0, random.uniform(12, 18) - datetime.now().minute) * 60)
        current_hour = datetime.now().hour
        while datetime.now().hour == current_hour:
            try:
                total_claimed = await claim_pumpkins(user)
            except Exception:
                logger.opt(colors=True, exception=True).warning(f"{prefix} Failed to claim pumpkins")
                logger.info(f"{prefix} Waiting for 5 minutes before retrying...")
                await anyio.sleep(60 * 5)
                continue

            if total_claimed == 100:
                logger.success(f"{prefix} Already claimed all pumpkins.")
                return

            logger.info(f"{prefix} Claimed <y>{total_claimed}</> pumpkins so far.")
            logger.info(f"{prefix} Waiting for the next claim attempt...")
            await anyio.sleep(60 * 10)


async def setup_pumpkin_event() -> None:
    now = datetime.now(UTC)
    if now >= EVENT_END:
        logger.info("Pumpkin event has ended.")
        return

    delay = random.uniform(60, 180)
    logger.info(f"Pumpkin event is active. Starting in {delay / 60:.2f} minutes...")
    await anyio.sleep(delay)

    async with anyio.create_task_group() as tg:
        for user in Config.load().users:
            logger.opt(colors=True).info(f"Starting pumpkin claim loop for user: <lm>{escape_tag(user.identifier)}</>")
            tg.start_soon(pumpkin_claim_loop, user)
            await anyio.sleep(30)
