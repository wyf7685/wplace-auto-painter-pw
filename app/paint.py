import random
from typing import NoReturn

import anyio

from .config import UserConfig
from .highlight import Highlight
from .log import escape_tag, logger
from .page import WplacePage, ZoomLevel, fetch_user_info
from .template import calc_template_diff, group_adjacent
from .utils import with_semaphore

logger = logger.opt(colors=True)


@with_semaphore(1)
async def paint_pixels(user: UserConfig, zoom: ZoomLevel):
    user_info = await fetch_user_info(user.credentials)
    logger.info(f"Logged in as: {Highlight.apply(user_info)}")
    logger.info(f"Current charge: <y>{user_info.charges.count:.2f}</>/<y>{user_info.charges.max}</>")
    logger.info(f"Remaining: <y>{user_info.charges.remaining_secs():.2f}</>s")

    diff = await calc_template_diff(user.template, include_pixels=True)
    for entry in sorted(diff, key=lambda e: e.count, reverse=True):
        if entry.name in user_info.own_colors:
            logger.info(f"Select color: <g>{entry.name}</> with <y>{entry.count}</> pixels to paint.")
            break
    else:
        logger.warning("No available colors to paint the template.")
        return

    coords = group_adjacent(entry.pixels)[0]
    pixels_to_paint = min((int(user_info.charges.count) - random.randint(5, 10)), len(coords) - 1)
    if pixels_to_paint < 10:
        logger.warning("Not enough charges to paint pixels.")
        return
    logger.info(f"Preparing to paint <y>{pixels_to_paint}</> pixels...")

    coord = user.template.coords.offset(*coords[0])
    async with WplacePage(user.credentials, entry.name, coord, zoom).begin() as page:
        delay = random.uniform(1, 10)
        logger.info(f"Waiting for <y>{delay:.2f}</> seconds before painting...")
        await anyio.sleep(delay)
        await page.find_and_click_paint_btn()

        await page.click_current_pixel()
        for idx in range(1, pixels_to_paint):
            prev_x, prev_y = coords[idx - 1]
            curr_x, curr_y = coords[idx]
            await page.move_by_pixel(curr_x - prev_x, curr_y - prev_y)
            await page.click_current_pixel()
            logger.info(f"Clicked pixel #<g>{idx + 1}</> at <y>{page.current_coord.human_repr()}</>")

        delay = random.uniform(1, 10)
        logger.info(f"Waiting for <y>{delay:.2f}</> seconds before submitting...")
        await anyio.sleep(delay)
        await page.find_and_click_paint_btn()
        await anyio.sleep(1)  # wait for submit

    user_info = await fetch_user_info(user.credentials)
    logger.info(f"Current charge: <y>{user_info.charges.count:.2f}</>/<y>{user_info.charges.max}</>")
    logger.info(f"Remaining: <y>{user_info.charges.remaining_secs():.2f}</>s")
    wait_secs = user_info.charges.remaining_secs() - random.uniform(10, 20) * 60
    logger.info(f"Next painting session in <y>{wait_secs / 60:.2f}</> minutes.")
    return wait_secs


async def paint_loop(user: UserConfig, zoom: ZoomLevel) -> NoReturn:
    prefix = f"<c>{escape_tag(user.identifier)}</> |"
    while True:
        try:
            logger.info(f"{prefix} Starting painting cycle...")
            wait_secs = await paint_pixels(user, zoom) or random.uniform(25 * 60, 35 * 60)
            logger.info(f"{prefix} Sleeping for <y>{wait_secs / 60:.2f}</> minutes...")
            await anyio.sleep(wait_secs)
        except Exception:
            logger.exception(f"{prefix} An error occurred")
