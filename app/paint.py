import contextlib
import hashlib
import random
import time
from collections.abc import Callable, Generator
from typing import Any

import anyio

from .config import TemplateConfig, UserConfig
from .consts import COLORS_ID, PAID_COLORS
from .exception import ShoudQuit
from .highlight import Highlight
from .log import escape_tag, logger
from .page import WplacePage, ZoomLevel, fetch_user_info
from .resolver import JsResolver
from .schemas import WplaceUserInfo
from .template import calc_template_diff, group_adjacent

logger = logger.opt(colors=True)
color_in_use: set[str] = set()


def pixels_to_paint_arg(template: TemplateConfig, color_id: int, pixels: list[tuple[int, int]]) -> list[dict[str, Any]]:
    base = template.coords
    result = []
    for x, y in pixels:
        coord = base.offset(x, y)
        item = {"tile": [coord.tlx, coord.tly], "season": 0, "colorIdx": color_id, "pixel": [coord.pxx, coord.pxy]}
        result.append(item)
    return result


async def get_user_info(user: UserConfig) -> WplaceUserInfo:
    prefix = f"<lm>{escape_tag(user.identifier)}</> |"
    user_info = await fetch_user_info(user.credentials)
    logger.debug(f"{prefix} Fetched user info: {Highlight.apply(user_info)}")
    logger.info(f"{prefix} Current droplets: 💧 <y>{user_info.droplets}</>")
    logger.info(f"{prefix} Current charge: 🎨 <y>{user_info.charges.count:.2f}</>/<y>{user_info.charges.max}</>")
    logger.info(f"{prefix} Remaining: <y>{user_info.charges.remaining_secs():.2f}</>s")
    if user_info.banned:
        logger.warning(f"{prefix} User is banned from painting!")
        raise ShoudQuit("User is banned from painting")
    return user_info


@contextlib.contextmanager
def claim_painting_color(name: str) -> Generator[Callable[[], None]]:
    color_in_use.add(name)
    released = False

    def release() -> None:
        nonlocal released
        if not released:
            color_in_use.discard(name)
            released = True

    try:
        yield release
    finally:
        release()


async def paint_pixels(user: UserConfig, user_info: WplaceUserInfo, zoom: ZoomLevel) -> float | None:
    resolved_js = await JsResolver().resolve()
    logger.info(f"Resolved paint functions: <c>{escape_tag(repr(resolved_js))}</>")

    diff = await calc_template_diff(user.template, include_pixels=True)
    for entry in sorted(diff, key=lambda e: (e.is_paid, e.name in user_info.own_colors, e.count), reverse=True):
        if entry.count > 0 and entry.name in user_info.own_colors and entry.name not in color_in_use:
            logger.info(f"Select color: <g>{entry.name}</> with <y>{entry.count}</> pixels to paint.")
            break
    else:
        logger.warning("No available colors to paint the template.")
        return None

    with claim_painting_color(entry.name) as release_color:
        coords = group_adjacent(entry.pixels)[0]
        pixels_to_paint = min((int(user_info.charges.count) - random.randint(5, 10)), len(coords) - 1)
        if pixels_to_paint < 10:
            logger.warning("Not enough pixels to paint.")
            return None
        logger.info(f"Preparing to paint <y>{pixels_to_paint}</> pixels...")

        script_data = {
            "btn": f"paint-button-{int(time.time())}",
            "a": pixels_to_paint_arg(user.template, COLORS_ID[entry.name], coords[:pixels_to_paint]),
            "f": hashlib.sha256(str(user_info.id).encode()).hexdigest()[:32],
            "r": resolved_js,
        }

        coord = user.template.coords.offset(*coords[0])
        page = WplacePage(user.credentials, entry.name, coord, zoom)
        async with page.begin(script_data, entry.name in PAID_COLORS) as page:
            delay = random.uniform(3, 10)
            logger.info(f"Waiting for <y>{delay:.2f}</> seconds before painting...")
            await anyio.sleep(delay)

            async with page.open_paint_panel():
                prev_x, prev_y = coords[0]
                for idx in range(pixels_to_paint):
                    curr_x, curr_y = coords[idx]
                    await page.move_by_pixel(curr_x - prev_x, curr_y - prev_y)
                    await page.click_current_pixel()
                    logger.debug(f"Clicked pixel #<g>{idx + 1}</> at <y>{page.current_coord.human_repr()}</>")
                    prev_x, prev_y = curr_x, curr_y

                delay = random.uniform(3, 10)
                logger.info(f"Waiting for <y>{delay:.2f}</> seconds before submitting...")
                await anyio.sleep(delay)
                await page.submit_paint()
                release_color()

            user_info = await get_user_info(user)
            wait_secs = user_info.charges.remaining_secs() - random.uniform(10, 20) * 60
            logger.info(f"Next painting session in <y>{wait_secs / 60:.2f}</> minutes.")
            return wait_secs


async def paint_loop(user: UserConfig, zoom: ZoomLevel = ZoomLevel.Z_15) -> None:
    prefix = f"<lm>{escape_tag(user.identifier)}</> |"
    while True:
        try:
            logger.info(f"{prefix} Starting painting cycle...")

            user_info = await get_user_info(user)
            if user_info.charges.count < 10:
                logger.warning(f"{prefix} Not enough charges to paint pixels.")
                wait_secs = max(600, user_info.charges.remaining_secs() - random.uniform(10, 20) * 60)
            else:
                wait_secs = await paint_pixels(user, user_info, zoom)
                if wait_secs is None or wait_secs < 0:
                    wait_secs = random.uniform(25 * 60, 35 * 60)

            logger.info(f"{prefix} Sleeping for <y>{wait_secs / 60:.2f}</> minutes...")
            await anyio.sleep(wait_secs)

        except ShoudQuit:
            logger.opt(exception=True).warning(f"{prefix} Received shutdown signal, exiting paint loop.")
            break

        except Exception:
            logger.exception(f"{prefix} An error occurred")
            delay = random.uniform(1 * 60, 3 * 60)
            logger.info(f"{prefix} Sleeping for <y>{delay / 60:.2f}</> minutes before retrying...")
            await anyio.sleep(delay)
