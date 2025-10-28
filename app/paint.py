import random

import anyio

from app.highlight import Highlight

from .config import config
from .log import logger
from .page import WplacePage, ZoomLevel, fetch_user_info
from .template import group_adjacent, calc_template_diff


async def paint_pixels(zoom: ZoomLevel):
    user_info = await fetch_user_info(config.credentials)
    logger.opt(colors=True).info(f"Logged in as: {Highlight.apply(user_info)}")
    logger.opt(colors=True).info(f"Current charge: <y>{user_info.charges.count:.2f}</>/<y>{user_info.charges.max}</>")
    logger.opt(colors=True).info(f"Remaining: <y>{user_info.charges.remaining_secs():.2f}</>s")

    diff = await calc_template_diff(config.template, include_pixels=True)
    for entry in sorted(diff, key=lambda e: e.count, reverse=True):
        if entry.name in user_info.own_colors:
            logger.opt(colors=True).info(f"Select color: <g>{entry.name}</> with <y>{entry.count}</> pixels to paint.")
            break
    else:
        logger.warning("No available colors to paint the template.")
        return

    coords = group_adjacent(entry.pixels)[0]
    pixels_to_paint = min((int(user_info.charges.count) - random.randint(5, 10)), len(coords) - 1)
    if pixels_to_paint < 10:
        logger.warning("Not enough charges to paint pixels.")
        return
    logger.opt(colors=True).info(f"Preparing to paint <y>{pixels_to_paint}</> pixels...")

    coord = config.template.coords.offset(*coords[0])
    async with WplacePage(config.credentials, entry.name, coord, zoom).begin() as page:
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

        delay = random.uniform(1, 10)
        logger.opt(colors=True).info(f"Waiting for <y>{delay:.2f}</> seconds before submitting...")
        await anyio.sleep(delay)
        await page.find_and_click_paint_btn()
        await anyio.sleep(1)  # wait for submit
