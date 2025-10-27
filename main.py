import contextlib
import random
import anyio

from app.browser import WplacePage, ZoomParams
from app.config import config
from app.log import logger
from app.template import (  # , select_outline_from_group
    get_color_location,
    group_adjacent,
)
from app.utils import normalize_color_name


async def test_zoom(page: WplacePage) -> None:
    await anyio.sleep(0.5)
    await page.find_and_click_paint_btn()
    await page.click_current_pixel()
    for idx in range(20):
        await page.pixel_move(1, 1)
        await page.click_current_pixel()
        logger.info(f"Clicked pixel #{idx + 1} at {page.current_coord.human_repr()}")
        # input()


async def main():
    color = normalize_color_name("black")
    assert color is not None, "Color not found"

    coords = await get_color_location(config.template, color)
    if not coords:
        logger.info(f"No pixels found for color '{color}' in the template area.")
        return

    coords = group_adjacent(coords)[0]

    coord = config.template.coords.offset(*coords[0])
    async with WplacePage(config.credentials, coord, ZoomParams.Z_15).begin() as page:
        await test_zoom(page)
        input()

        user_info = await page.fetch_user_info()
        logger.info(f"Logged in as: {user_info!r}")
        logger.info(
            f"Current charge: {user_info.charges.count:.2f}/{user_info.charges.max}"
        )
        pixels_to_paint = min(
            (int(user_info.charges.count) - random.randint(5, 10)),
            len(coords) - 1,
        )
        if pixels_to_paint < 10:
            logger.warning("Not enough charges to paint pixels.")
            return
        logger.info(f"Preparing to paint {pixels_to_paint} pixels...")

        await anyio.sleep(0.5)
        await page.find_and_click_paint_btn()

        await page.click_current_pixel()
        for idx in range(1, pixels_to_paint):
            prev_x, prev_y = coords[idx - 1]
            curr_x, curr_y = coords[idx]
            await page.pixel_move(curr_x - prev_x, 0)
            await page.pixel_move(0, curr_y - prev_y)
            await page.click_current_pixel()
            logger.info(
                f"Clicked pixel #{idx + 1} at {page.current_coord.human_repr()}"
            )
        if input("Submit? [y|N] ").lower() == "y":
            await page.find_and_click_paint_btn()
            await anyio.sleep(1)  # wait for submit

        input()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        anyio.run(main)
