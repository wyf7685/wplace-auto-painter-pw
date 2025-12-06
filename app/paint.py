import contextlib
import hashlib
import random
import time
from collections.abc import AsyncGenerator, Iterable
from datetime import datetime, timedelta
from typing import Any

import anyio
from bot7685_ext.wplace import ColorEntry, group_adjacent
from bot7685_ext.wplace.consts import COLORS_NAME, ColorName

from app.purchase import do_purchase
from app.utils import is_token_expired

from .config import Config, TemplateConfig, UserConfig
from .exception import ShoudQuit
from .highlight import Highlight
from .log import escape_tag, logger
from .page import WplacePage, fetch_user_info
from .resolver import JsResolver
from .schemas import WplaceUserInfo
from .template import calc_template_diff

logger = logger.opt(colors=True)
COLORS_CLAIMER_LOCK = anyio.Lock()
COLORS_LOCK: dict[ColorName, anyio.Lock] = {name: anyio.Lock() for name in COLORS_NAME.values()}


def pixels_to_paint_arg(template: TemplateConfig, pixels: list[tuple[int, int, int]]) -> list[dict[str, Any]]:
    base, _ = template.get_coords()
    result = []
    for x, y, color_id in pixels:
        coord = base.offset(x, y)
        item = {
            "tile": [coord.tlx, coord.tly],
            "season": 0,
            "colorIdx": color_id,
            "pixel": [coord.pxx, coord.pxy],
        }
        result.append(item)
    return result


async def get_user_info(user: UserConfig) -> WplaceUserInfo:
    prefix = f"<lm>{escape_tag(user.identifier)}</> |"
    user_info = await fetch_user_info(user.credentials)
    logger.debug(f"{prefix} Fetched user info: {Highlight.apply(user_info)}")
    logger.info(f"{prefix} Current droplets: 💧 <y>{user_info.droplets}</>")
    charges = user_info.charges
    remaining_secs = charges.remaining_secs()
    recover_time = (datetime.now() + timedelta(seconds=remaining_secs)).strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"{prefix} Current charge: 🎨 <y>{charges.count:.2f}</>/<y>{charges.max}</> ")
    logger.info(f"{prefix} Remaining: ⏱️ <y>{remaining_secs:.2f}</>s, recovers at <g>{recover_time}</>")
    return user_info


@contextlib.asynccontextmanager
async def claim_painting_color(names: Iterable[ColorName]) -> AsyncGenerator[None]:
    async with contextlib.AsyncExitStack() as stack:
        async with COLORS_CLAIMER_LOCK:
            for name in names:
                await stack.enter_async_context(COLORS_LOCK[name])
        yield


async def select_paint_color(
    user: UserConfig, user_info: WplaceUserInfo
) -> tuple[TemplateConfig, list[ColorEntry]] | None:
    def sort_key(entry: ColorEntry) -> tuple[int, ...]:
        return (
            -(
                user.preferred_colors.index(entry.name)
                if entry.name in user.preferred_colors
                else len(user.preferred_colors) + 1
            ),
            entry.is_paid,
            entry.name in user_info.own_colors,
            entry.count,
        )

    async def select(template: TemplateConfig) -> list[ColorEntry] | None:
        diff = await calc_template_diff(template, include_pixels=True)
        entries: list[ColorEntry] = []
        for entry in sorted(diff, key=sort_key, reverse=True):
            if entry.count > 0 and entry.name in user_info.own_colors and not COLORS_LOCK[entry.name].locked():
                logger.info(f"Select color: <g>{entry.name}</> with <y>{entry.count}</> pixels to paint.")
                entries.append(entry)
            if sum(e.count for e in entries) >= user_info.charges.count * 0.9:
                break
        return entries or None

    if user.selected_area is not None:
        logger.info(f"Using selected area for painting: <g>{user.selected_area}</>")
        template = user.template.crop(user.selected_area)
        if entry := await select(template):
            return template, entry

        logger.warning("No available colors to paint in the selected area, falling back to full template.")

    if entry := await select(user.template):
        return user.template, entry

    logger.warning("No available colors to paint the template.")
    return None


async def paint_pixels(user: UserConfig, user_info: WplaceUserInfo) -> None:
    resolved_js = await JsResolver().resolve()
    logger.info(f"Resolved paint functions: <c>{escape_tag(repr(resolved_js))}</>")

    if (selected := await select_paint_color(user, user_info)) is None:
        return
    template, entries = selected

    async with claim_painting_color(entry.name for entry in entries):
        groups = await group_adjacent([(x, y, e.id) for e in entries for x, y in e.pixels], 100, 30.0)
        pixels = sorted((p for g in groups for p in g), key=lambda p: user.preferred_colors_rank[p[2]])
        pixels_to_paint = min(int(user_info.charges.count), len(pixels))
        if pixels_to_paint <= 0:
            logger.warning("Not enough pixels to paint.")
            return
        logger.info(f"Preparing to paint <y>{pixels_to_paint}</> pixels...")
        pixels = pixels[:pixels_to_paint]

        script_data = {
            "btn": f"paint-button-{int(time.time())}",
            "a": pixels_to_paint_arg(template, pixels),
            "f": hashlib.sha256(str(user_info.id).encode()).hexdigest()[:32],
            "r": resolved_js,
        }

        coord = template.get_coords()[0].offset(*pixels[0][:2])
        async with WplacePage(user.credentials, coord).begin(script_data) as page:
            delay = random.uniform(3, 7)
            logger.info(f"Waiting for <y>{delay:.2f}</> seconds before painting...")
            await anyio.sleep(delay)

            async with page.open_paint_panel() as paint:
                prev_x, prev_y, prev_color = pixels[0]
                await anyio.sleep(random.uniform(0.5, 1.5))
                await paint.select_color(prev_color)
                for curr_x, curr_y, curr_color in pixels:
                    if prev_color != curr_color:
                        await anyio.sleep(random.uniform(0.5, 1.5))
                        logger.info(
                            f"Switching color: <g>{COLORS_NAME[prev_color]}</>(id=<c>{prev_color}</>) "
                            f"-> <g>{COLORS_NAME[curr_color]}</>(id=<c>{curr_color}</>)"
                        )
                        await paint.select_color(curr_color)
                        prev_color = curr_color
                        await anyio.sleep(random.uniform(0.5, 1.5))
                    await page.move_by_pixel(curr_x - prev_x, curr_y - prev_y)
                    await page.click_current_pixel()
                    prev_x, prev_y = curr_x, curr_y

                delay = random.uniform(3, 7)
                logger.info(f"Waiting for <y>{delay:.2f}</> seconds before submitting...")
                await anyio.sleep(delay)
                await paint.submit()


async def paint_loop(user: UserConfig) -> None:
    prefix = f"<lm>{escape_tag(user.identifier)}</> |"
    while True:
        try:
            logger.info(f"{prefix} Starting painting cycle...")
            logger.debug(f"{prefix} User config: {Highlight.apply(user)}")

            if is_token_expired(user.credentials.token.get_secret_value()):
                logger.warning(f"{prefix} Token expired, stopping paint loop.")
                raise ShoudQuit("Token expired")

            user_info = await get_user_info(user)
            if user_info.charges.count < 30:
                logger.warning(f"{prefix} Not enough charges to paint pixels.")
                wait_secs = max(600.0, user_info.charges.remaining_secs() - random.uniform(10, 20) * 60)
            else:
                await paint_pixels(user, user_info)
                logger.info(f"{prefix} Painting completed, refetching user info...")
                user_info = await get_user_info(user)

                wait_secs = user_info.charges.remaining_secs() * random.uniform(0.85, 0.95)

            if user.auto_purchase is not None:
                logger.info(f"{prefix} Checking auto-purchase: {Highlight.apply(user.auto_purchase)}")
                if await do_purchase(user, user_info):
                    logger.info(f"{prefix} Purchase completed, refetching user info...")
                    user_info = await get_user_info(user)
                else:
                    logger.info(f"{prefix} No purchase made.")

                wait_secs = user_info.charges.remaining_secs() * random.uniform(0.85, 0.95)

            if user_info.charges.count >= 30:
                logger.info(f"{prefix} Still have enough charges to paint, continuing immediately.")
                continue

            wakeup_time = datetime.now() + timedelta(seconds=wait_secs)
            logger.info(f"{prefix} Sleeping for <y>{wait_secs / 60:.2f}</> minutes...")
            logger.info(f"{prefix} Next paint cycle at <g>{wakeup_time:%Y-%m-%d %H:%M:%S}</>.")
            await anyio.sleep(wait_secs)

        except ShoudQuit:
            logger.opt(colors=True, exception=True).warning(f"{prefix} Received shutdown signal, exiting paint loop.")
            break

        except Exception:
            logger.exception(f"{prefix} An error occurred")
            delay = random.uniform(1 * 60, 3 * 60)
            logger.info(f"{prefix} Sleeping for <y>{delay / 60:.2f}</> minutes before retrying...")
            await anyio.sleep(delay)


async def setup_paint() -> None:
    async with anyio.create_task_group() as tg:
        for user in Config.load().users:
            logger.info(f"Starting paint loop for user: <lm>{escape_tag(user.identifier)}</>")
            tg.start_soon(paint_loop, user)
            await anyio.sleep(30)
