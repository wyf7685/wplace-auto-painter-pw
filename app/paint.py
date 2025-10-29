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

from app.schemas import WplaceUserInfo

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


class JsResolver:
    PATTERN_CHUNK_NAME = re.compile(r"_app/immutable/(.+?)\.js")
    PATTERN_PAINT_FN = re.compile(r"await\s+([a-zA-Z0-9_$]+)\.paint\s*\(")

    async def prepare_chunks(self) -> None:
        async def download_js_chunk(chunk_name: str) -> None:
            url = f"https://wplace.live/_app/immutable/{chunk_name}"
            response = await client.get(url)
            js_code = response.raise_for_status().text
            file = self.tempdir / chunk_name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text(js_code, encoding="utf-8")

        html = (await anyio.to_thread.run_sync(cloudscraper.create_scraper().get, "https://wplace.live/")).text
        async with httpx.AsyncClient() as client, anyio.create_task_group() as tg:
            for match in self.PATTERN_CHUNK_NAME.finditer(html):
                chunk_name = f"{match.group(1)}.js"
                tg.start_soon(download_js_chunk, chunk_name)

    def find_paint_fn(self) -> tuple[str, str]:
        for file in (self.tempdir / "nodes").glob("*.js"):
            if match := self.PATTERN_PAINT_FN.search(file.read_text(encoding="utf-8")):
                obj_name = match.group(1)
                break
        else:
            raise ValueError("paint function object not found")

        pattern = (
            r"import\s*\{[^}]*?\b([a-zA-Z0-9_$]+)\s+as\s+"
            + re.escape(obj_name)
            + r"[^}]*?\}\s*from\s*[\"']([^\"']+)[\"'];"
        )
        match = re.search(pattern, file.read_text(encoding="utf-8"))
        if match is None:
            raise ValueError("import source for paint function object not found")

        source_name = match.group(1)
        chunk_name = (file.parent / match.group(2)).resolve().relative_to(self.tempdir.resolve()).as_posix()
        chunk_url = f"https://wplace.live/_app/immutable/{chunk_name}"
        return source_name, chunk_url

    def find_worker_fn(self) -> tuple[str, str]:
        for file in self.tempdir.glob("*/*.js"):
            content = file.read_text("utf-8")
            if ("navigator.serviceWorker.controller" in content) and (
                match := re.search(r"function ([a-zA-Z0-9_$]+)\([a-zA-Z0-9_$]+\)\{const .+=Math.random\(\)", content)
            ):
                func_name = match.group(1)
                break
        else:
            raise ValueError("service worker function not found")

        pattern = (
            r"function ([a-zA-Z0-9_$]+)\([a-zA-Z0-9_$]+\)\s*\{return "
            + re.escape(func_name)
            + r"\(\{type:\s*['\"]paintPixels['\"],data:\s*q\}\)\}"
        )
        match = re.search(pattern, content)
        if match is None:
            raise ValueError("wrapper function not found")
        wrapper_name = match.group(1)

        pattern = r"export\s*\{[^}]*?\b,?" + re.escape(wrapper_name) + r"\s+as\s+([a-zA-Z0-9_$]+)[^}]*?\};"
        match = re.search(pattern, content)
        if match is None:
            raise ValueError("exported name for wrapper not found")

        chunk_name = file.resolve().relative_to(self.tempdir.resolve()).as_posix()
        chunk_url = f"https://wplace.live/_app/immutable/{chunk_name}"
        return (match.group(1), chunk_url)

    async def resolve(self) -> list[str]:
        with tempfile.TemporaryDirectory() as tempdir:
            self.tempdir = Path(tempdir)
            await self.prepare_chunks()
            return [*self.find_paint_fn(), *self.find_worker_fn()]


@with_semaphore(1)
async def paint_pixels(user: UserConfig, user_info: WplaceUserInfo, zoom: ZoomLevel) -> float | None:
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

    resolved = await JsResolver().resolve()
    logger.info(f"Resolved paint functions: <c>{escape_tag(repr(resolved))}</>")
    script_data = {
        "btn": f"paint-button-{int(time.time())}",
        "a": pixels_to_paint_arg(user.template, COLORS_ID[entry.name], coords[:pixels_to_paint]),
        "f": hashlib.sha256(str(user_info.id).encode()).hexdigest()[:32],
        "r": resolved,
    }

    coord = user.template.coords.offset(*coords[0])
    async with WplacePage(user.credentials, entry.name, coord, zoom).begin(script_data) as page:
        delay = random.uniform(1, 10)
        logger.info(f"Waiting for <y>{delay:.2f}</> seconds before painting...")
        await anyio.sleep(delay)
        await page.find_and_click_paint_btn()

        prev_x, prev_y = coords[0]
        for idx in range(pixels_to_paint):
            curr_x, curr_y = coords[idx]
            await page.move_by_pixel(curr_x - prev_x, curr_y - prev_y)
            await page.click_current_pixel()
            logger.debug(f"Clicked pixel #<g>{idx + 1}</> at <y>{page.current_coord.human_repr()}</>")
            prev_x, prev_y = curr_x, curr_y

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


async def paint_loop(user: UserConfig, zoom: ZoomLevel = ZoomLevel.Z_15) -> NoReturn:
    prefix = f"<m>{escape_tag(user.identifier)}</> |"
    while True:
        try:
            logger.info(f"{prefix} Starting painting cycle...")

            user_info = await fetch_user_info(user.credentials)
            logger.info(f"Logged in as: {Highlight.apply(user_info)}")
            logger.info(f"Current charge: <y>{user_info.charges.count:.2f}</>/<y>{user_info.charges.max}</>")
            logger.info(f"Remaining: <y>{user_info.charges.remaining_secs():.2f}</>s")
            if user_info.charges.count < 10:
                logger.warning(f"{prefix} Not enough charges to paint pixels.")
                wait_secs = max(600, user_info.charges.remaining_secs() - random.uniform(10, 20) * 60)
            else:
                wait_secs = await paint_pixels(user, user_info, zoom)
                if wait_secs is None or wait_secs < 0:
                    wait_secs = random.uniform(25 * 60, 35 * 60)

            logger.info(f"{prefix} Sleeping for <y>{wait_secs / 60:.2f}</> minutes...")
            await anyio.sleep(wait_secs)

        except Exception:
            logger.exception(f"{prefix} An error occurred")
