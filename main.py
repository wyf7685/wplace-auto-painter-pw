import contextlib

import anyio

from app.browser import shutdown_playwright
from app.config import Config, UserConfig
from app.log import escape_tag, logger
from app.page import WplacePage, ZoomLevel
from app.paint import paint_loop
from app.template import get_color_location, group_adjacent
from app.utils import normalize_color_name


async def test_zoom(user: UserConfig) -> None:
    color_name = normalize_color_name("black")
    assert color_name is not None, "Color not found"
    coords = await get_color_location(user.template, color_name)
    if not coords:
        logger.info(f"No pixels found for color '{color_name}' in the template area.")
        return

    # find the largest group
    coords = group_adjacent(coords)[0]

    coord = user.template.coords.offset(*coords[0])
    page = WplacePage(user.credentials, color_name, coord, ZoomLevel.Z_15)
    async with page.begin({"user_id": "111", "btn_id": "paint-button-7685", "reqs": []}) as page:
        logger.info(f"Current viewport: {page.current_page_viewport}")
        await anyio.sleep(0.5)
        await page.find_and_click_paint_btn()
        await page.click_current_pixel()
        for idx in range(70):
            await page.move_by_pixel(2, 2)
            await page.click_current_pixel()
            logger.info(f"Clicked pixel #{idx + 1} at {page.current_coord.human_repr()}")
        input()


async def main() -> None:
    # await test_zoom(Config.load().users[0])
    # return

    try:
        async with anyio.create_task_group() as tg:
            for user in Config.load().users:
                logger.opt(colors=True).info(f"Starting paint loop for user: <m>{escape_tag(user.identifier)}</>")
                tg.start_soon(paint_loop, user, ZoomLevel.Z_15)
    except* KeyboardInterrupt:
        logger.info("Shutting down...")

    await shutdown_playwright()


if __name__ == "__main__":
    with contextlib.suppress(KeyboardInterrupt):
        anyio.run(main)
