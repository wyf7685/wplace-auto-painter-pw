import random
from datetime import UTC, datetime

import anyio
import cloudscraper
from pydantic import BaseModel, TypeAdapter, computed_field

from app.assets import assets
from app.browser import get_browser
from app.config import UserConfig, WplaceCredentials
from app.exception import FetchFailed
from app.highlight import Highlight
from app.log import logger
from app.utils import WplacePixelCoords, requests_proxies, run_sync

# Event ends at Friday, Jan 2 00:00 AM (UTC)
EVENT_END = datetime(2025, 1, 2, tzinfo=UTC)
logger = logger.opt(colors=True)


class ChristmasLocation(BaseModel):
    id: int
    latitude: float
    longitude: float
    claimed: bool

    @computed_field
    @property
    def coords(self) -> WplacePixelCoords:
        return WplacePixelCoords.from_lat_lon(self.latitude, self.longitude)


_ta = TypeAdapter(list[ChristmasLocation])


@run_sync
def fetch_christmas_locations(credentials: WplaceCredentials) -> list[ChristmasLocation]:
    try:
        resp = cloudscraper.create_scraper().get(
            "https://backend.wplace.live/event/christmas/locations",
            cookies=credentials.to_requests_cookies(),
            proxies=requests_proxies(),
        )
        resp.raise_for_status()
        data = resp.json()
    except Exception as e:
        raise RuntimeError(f"Failed to load claimed pumpkins: {e}") from e

    try:
        return _ta.validate_python(data)
    except Exception as e:
        raise FetchFailed("Failed to parse Christmas locations") from e


async def claim_presents(user: UserConfig) -> None:
    prefix = f"<lm>{user.identifier}</> | <ly>Christmas</> |"

    locations = await fetch_christmas_locations(user.credentials)
    unclaimed = [loc for loc in locations if not loc.claimed]
    if not unclaimed:
        logger.info(f"{prefix} All presents have already been claimed.")
        return

    async with (
        get_browser() as browser,
        await browser.new_context(viewport={"width": 1280, "height": 720}, java_script_enabled=True) as context,
    ):
        await context.add_init_script(assets.page_init())
        await context.add_cookies(user.credentials.to_pw_cookies())

        async with await context.new_page() as page:
            for loc in unclaimed:
                logger.info(f"{prefix} Claiming present: {Highlight.apply(loc)}")
                await page.goto(loc.coords.to_share_url(), wait_until="networkidle")
                if (viewport := page.viewport_size) is None:
                    raise RuntimeError("Failed to get viewport size")
                await page.mouse.click(viewport["width"] // 2, viewport["height"] // 2)
                logger.info(f"{prefix} Claimed present at location ID <y>{loc.id}</>.")
                await anyio.sleep(random.uniform(1.5, 3.5))  # Small delay between claims
