import contextlib
import random

import anyio

from app.browser import shutdown_playwright
from app.config import config
from app.log import logger
from app.page import WplacePage, ZoomParams
from app.paint import paint_pixels
from app.template import get_color_location, group_adjacent
from app.utils import normalize_color_name


async def test_zoom(page: WplacePage) -> None:
    color_name = normalize_color_name("black")
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
        await anyio.sleep(0.5)
        await page.find_and_click_paint_btn()
        await page.click_current_pixel()
        for idx in range(20):
            await page._move_by_pixel(1, 1)
            await page.click_current_pixel()
            logger.info(f"Clicked pixel #{idx + 1} at {page.current_coord.human_repr()}")

    input()


async def main() -> None:
    while True:
        try:
            logger.info("Starting painting cycle...")
            await paint_pixels("black")
            wait_secs = random.uniform(25 * 60, 35 * 60)
            logger.info(f"Sleeping for {wait_secs / 60:.2f} minutes...")
            await anyio.sleep(wait_secs)
        except KeyboardInterrupt:
            logger.info("Received exit signal. Shutting down...")
            break
        except Exception as e:
            logger.exception(f"An error occurred: {e}")

    await shutdown_playwright()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        anyio.run(main)
