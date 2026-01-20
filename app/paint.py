import contextlib
import hashlib
import random
import time
import uuid
from collections.abc import AsyncGenerator, Iterable
from datetime import datetime, timedelta
from typing import Any

import anyio
from bot7685_ext.wplace import ColorEntry, group_adjacent
from bot7685_ext.wplace.consts import COLORS_NAME, ColorName

from app.config import Config, TemplateConfig, UserConfig
from app.exception import PaintFinished, ShouldQuit, TokenExpired
from app.log import escape_tag, logger
from app.page import WplacePage, fetch_user_info
from app.purchase import do_purchase
from app.resolver import resolve_js
from app.schemas import WplaceUserInfo
from app.template import calc_template_diff
from app.utils import Highlight, is_token_expired
from app.utils.ansi_image import draw_ansi

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
        if entries := await select(template):
            return template, entries

        logger.warning("No available colors to paint in the selected area, falling back to full template.")

    if entries := await select(user.template):
        return user.template, entries

    logger.warning("No available colors to paint the template.")
    return None


async def paint_pixels(user: UserConfig, user_info: WplaceUserInfo) -> None:
    resolved_js = await resolve_js()
    logger.info(f"Resolved paint functions: <c>{escape_tag(repr(resolved_js))}</>")

    if (selected := await select_paint_color(user, user_info)) is None:
        raise PaintFinished("No colors available to paint")
    template, entries = selected

    logger.info("Template preview:")
    draw_ansi(template.load_im())

    async with claim_painting_color(entry.name for entry in entries):
        groups = await group_adjacent([(x, y, e.id) for e in entries for x, y in e.pixels])
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
            "t": f"data-{uuid.uuid4().hex[:8]}",
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
                raise TokenExpired("Token expired")

            user_info = await get_user_info(user)
            if should_paint := user_info.charges.count >= user.min_paint_charges:
                await paint_pixels(user, user_info)
                logger.info(f"{prefix} Painting completed, refetching user info...")
                user_info = await get_user_info(user)

                wait_secs = min(
                    user_info.charges.remaining_secs() * random.uniform(0.85, 0.95),
                    60 * 60 * 4 + random.uniform(-10, 10) * 60,
                )
            else:
                logger.warning(f"{prefix} Not enough charges to paint pixels.")
                logger.warning(f"{prefix} Minimum required charges: <y>{user.min_paint_charges}</>")
                wait_secs = max(600.0, user_info.charges.remaining_secs() - random.uniform(10, 20) * 60)

            if user.auto_purchase is not None:
                logger.info(f"{prefix} Checking auto-purchase: {Highlight.apply(user.auto_purchase)}")
                if await do_purchase(user, user_info):
                    logger.info(f"{prefix} Purchase completed, refetching user info...")
                    user_info = await get_user_info(user)
                else:
                    logger.info(f"{prefix} No purchase made.")

                wait_secs = min(
                    user_info.charges.remaining_secs() * random.uniform(0.85, 0.95),
                    60 * 60 * 4 + random.uniform(-10, 10) * 60,
                )

            if user_info.charges.count >= user.min_paint_charges:
                logger.info(
                    f"{prefix} Still have enough charges to paint (>=<y>{user.min_paint_charges}</>), "
                    "continuing immediately."
                )
                continue

            if should_paint and user.selected_area is not None:
                template = user.template.crop(user.selected_area)
                diff = await calc_template_diff(template, include_pixels=False)
                if diff := sorted(filter(lambda e: e.count, diff), key=lambda e: e.count, reverse=True)[:5]:
                    logger.info(f"{prefix} Top {len(diff)} colors needed in selected area:")
                    for idx, entry in enumerate(diff, 1):
                        logger.info(f" {idx}. <g>{entry.name}</>: <y>{entry.count}</> pixels")
                else:
                    logger.warning(f"{prefix} Selected area is fully painted, consider changing it.")

            wakeup_at = datetime.now() + timedelta(seconds=wait_secs)
            logger.info(f"{prefix} Sleeping for <y>{wait_secs / 60:.2f}</> minutes...")
            logger.info(f"{prefix} Next paint cycle at <g>{wakeup_at:%Y-%m-%d %H:%M:%S}</>.")
            await anyio.sleep(wait_secs)

        except ShouldQuit:
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
