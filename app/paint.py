import hashlib
import random
import re
import tempfile
import time
from pathlib import Path
from typing import Any, NoReturn

import anyio
import anyio.to_thread
import cloudscraper
import httpx

from .config import TemplateConfig, UserConfig
from .consts import COLORS_ID
from .highlight import Highlight
from .log import escape_tag, logger
from .page import WplacePage, ZoomLevel, fetch_user_info
from .template import calc_template_diff, group_adjacent
from .utils import with_semaphore

logger = logger.opt(colors=True)


def pixels_to_paint_arg(template: TemplateConfig, color_id: int, pixels: list[tuple[int, int]]) -> list[dict[str, Any]]:
    base = template.coords
    result = []
    for x, y in pixels:
        coord = base.offset(x, y)
        item = {"tile": [coord.tlx, coord.tly], "season": 0, "colorIdx": color_id, "pixel": [coord.pxx, coord.pxy]}
        result.append(item)
    return result


async def resolve_paint_fn() -> tuple[str, str]:
    with tempfile.TemporaryDirectory() as tempdir:
        tempdir = Path(tempdir)
        html = (await anyio.to_thread.run_sync(cloudscraper.create_scraper().get, "https://wplace.live/")).text

        async def download_js_chunk(chunk_name: str) -> None:
            url = f"https://wplace.live/_app/immutable/{chunk_name}"
            response = await client.get(url)
            js_code = response.raise_for_status().text
            file = tempdir / chunk_name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(js_code, encoding="utf-8")

        source_pattern = re.compile(r"_app/immutable/(.+?)\.js")
        async with httpx.AsyncClient() as client, anyio.create_task_group() as tg:
            for match in source_pattern.finditer(html):
                chunk_name = f"{match.group(1)}.js"
                tg.start_soon(download_js_chunk, chunk_name)

        pattern = re.compile(r"await\s+([a-zA-Z0-9_$]+)\.paint\s*\(")
        obj_name_gen = (
            (file, match.group(1))
            for file in (tempdir / "nodes").glob("*.js")
            for match in pattern.finditer(file.read_text(encoding="utf-8"))
        )
        if (obj := next(obj_name_gen, None)) is None:
            raise ValueError("paint function object not found")
        file, obj_name = obj

        if match := re.search(
            rf'import\s*\{{[^}}]*?\b([a-zA-Z0-9_$]+)\s+as\s+{re.escape(obj_name)}[^}}]*?\}}\s*from\s*["\']([^"\']+)["\'];',
            file.read_text(encoding="utf-8"),
        ):
            source_name = match.group(1)
            chunk_name = (file.parent / match.group(2)).resolve().relative_to(tempdir.resolve()).as_posix()
            chunk_url = f"https://wplace.live/_app/immutable/{chunk_name}"
            return source_name, chunk_url

        raise ValueError("import source for paint function object not found")


@with_semaphore(1)
async def paint_pixels(user: UserConfig, zoom: ZoomLevel) -> float | None:
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
        return None

    coords = group_adjacent(entry.pixels)[0]
    pixels_to_paint = min((int(user_info.charges.count) - random.randint(5, 10)), len(coords) - 1)
    if pixels_to_paint < 10:
        logger.warning("Not enough charges to paint pixels.")
        return None
    logger.info(f"Preparing to paint <y>{pixels_to_paint}</> pixels...")

    paint_obj_name, paint_module_url = await resolve_paint_fn()
    logger.info(f"Resolved paint function: <c>{paint_obj_name}</> from <y><u>{escape_tag(paint_module_url)}</></>")
    script_data = {
        "user_id": str(user_info.id),
        "btn_id": f"paint-button-{int(time.time())}",
        "paint_args": pixels_to_paint_arg(user.template, COLORS_ID[entry.name], coords[:pixels_to_paint]),
        "fp": hashlib.sha256(str(user_info.id).encode()).hexdigest()[:32],
        "module_url": paint_module_url,
        "obj_name": paint_obj_name,
    }

    coord = user.template.coords.offset(*coords[0])
    async with WplacePage(user.credentials, entry.name, coord, zoom).begin(script_data) as page:
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
        await page.submit_paint()

    user_info = await fetch_user_info(user.credentials)
    logger.info(f"Current charge: <y>{user_info.charges.count:.2f}</>/<y>{user_info.charges.max}</>")
    logger.info(f"Remaining: <y>{user_info.charges.remaining_secs():.2f}</>s")
    wait_secs = user_info.charges.remaining_secs() - random.uniform(10, 20) * 60
    logger.info(f"Next painting session in <y>{wait_secs / 60:.2f}</> minutes.")
    return wait_secs


async def paint_loop(user: UserConfig, zoom: ZoomLevel) -> NoReturn:
    prefix = f"<m>{escape_tag(user.identifier)}</> |"
    while True:
        try:
            logger.info(f"{prefix} Starting painting cycle...")
            wait_secs = await paint_pixels(user, zoom) or random.uniform(25 * 60, 35 * 60)
            logger.info(f"{prefix} Sleeping for <y>{wait_secs / 60:.2f}</> minutes...")
            await anyio.sleep(wait_secs)
        except Exception:
            logger.exception(f"{prefix} An error occurred")
