import random

import anyio

from app.highlight import Highlight

from .config import config
from .log import logger
from .page import WplacePage, ZoomParams
from .template import get_color_location, group_adjacent
from .utils import normalize_color_name


async def paint_pixels(name: str):
    color_name = normalize_color_name(name)
    assert color_name is not None, "Color not found"
    coords = await get_color_location(config.template, color_name)
    if not coords:
        logger.info(f"No pixels found for color '{color_name}' in the template area.")
        return

    # find the largest group
    coords = group_adjacent(coords)[0]

    coord = config.template.coords.offset(*coords[0])
    page = WplacePage(config.credentials, color_name, coord, ZoomParams.Z_15)
    async with page.begin() as page:
        user_info = await page.fetch_user_info()
        logger.opt(colors=True).info(f"Logged in as: {Highlight.apply(user_info)}")
        logger.opt(colors=True).info(
            f"Current charge: <y>{user_info.charges.count:.2f}</>/<y>{user_info.charges.max}</>"
        )
        logger.opt(colors=True).info(f"Remaining: <y>{user_info.charges.remaining_secs():.2f}</>s")
        pixels_to_paint = min(
            (int(user_info.charges.count) - random.randint(5, 10)),
            len(coords) - 1,
        )
        if pixels_to_paint < 10:
            logger.warning("Not enough charges to paint pixels.")
            return
        logger.opt(colors=True).info(f"Preparing to paint <y>{pixels_to_paint}</> pixels...")

        delay = random.uniform(1, 10)
        logger.opt(colors=True).info(f"Waiting for <y>{delay:.2f}</> seconds before painting...")
        await anyio.sleep(delay)
        await page.find_and_click_paint_btn()

        await page.click_current_pixel()
        for idx in range(1, pixels_to_paint):
            prev_x, prev_y = coords[idx - 1]
            curr_x, curr_y = coords[idx]
            await page.move_by_pixel(curr_x - prev_x, curr_y - prev_y)
            await page.click_current_pixel()
            logger.opt(colors=True).info(f"Clicked pixel #<g>{idx + 1}</> at <y>{page.current_coord.human_repr()}</>")

        await anyio.sleep(0.3)
        await page.find_and_click_paint_btn()
        await anyio.sleep(1)  # wait for submit
