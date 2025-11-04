import functools
import json
import re

import anyio
import anyio.to_thread
import cloudscraper
import httpx

from app.log import escape_tag, logger

from .config import DATA_DIR, Config
from .exception import ShoudQuit
from .utils import requests_proxies, with_semaphore

CHUNKS_DIR = DATA_DIR / "js_chunks"
CHUNK_ETAG_FILE = CHUNKS_DIR / "etag.json"
PATTERN_CHUNK_NAME = re.compile(r"_app/immutable/(.+?)\.js")


def load_chunk_etags() -> dict[str, str]:
    if not CHUNK_ETAG_FILE.exists():
        return {}

    return json.loads(CHUNK_ETAG_FILE.read_text(encoding="utf-8"))


def save_chunk_etags(etags: dict[str, str]) -> None:
    CHUNK_ETAG_FILE.write_text(json.dumps(etags), encoding="utf-8")


@with_semaphore(1)
async def prepare_chunks() -> None:
    resp = await anyio.to_thread.run_sync(
        functools.partial(
            cloudscraper.create_scraper().get,
            url="https://wplace.live/",
            proxies=requests_proxies(),
        )
    )
    resp.raise_for_status()
    html = resp.text
    chunks = {f"{match.group(1)}.js" for match in PATTERN_CHUNK_NAME.finditer(html)}
    etags = load_chunk_etags()
    for chunk_name in set(etags.keys()) - chunks:
        # Remove obsolete chunks
        del etags[chunk_name]
        (CHUNKS_DIR / chunk_name).unlink(missing_ok=True)

    async def download_js_chunk(chunk_name: str) -> None:
        file = CHUNKS_DIR / chunk_name
        file.parent.mkdir(parents=True, exist_ok=True)

        headers = (
            {"If-None-Match": etags[chunk_name]}
            if chunk_name in etags and file.exists() and file.stat().st_size > 0
            else {}
        )
        url = f"https://wplace.live/_app/immutable/{chunk_name}"
        response = await client.get(url, headers=headers)
        if response.status_code == 304:
            return  # Not modified

        response.raise_for_status()
        if etag := response.headers.get("ETag"):
            etags[chunk_name] = etag
        logger.opt(colors=True).debug(f"Downloaded JS chunk: <c>{escape_tag(chunk_name)}</>")
        file.write_text(response.text, encoding="utf-8")

    async with httpx.AsyncClient(proxy=Config.load().proxy) as client, anyio.create_task_group() as tg:
        for chunk_name in chunks:
            tg.start_soon(download_js_chunk, chunk_name)

    save_chunk_etags(etags)


async def resolve_pixel_map(fp: str) -> tuple[str, str]:  # chunk_url, modified_content
    await prepare_chunks()

    for file in (CHUNKS_DIR / "nodes").glob("*.js"):
        content = file.read_text(encoding="utf-8")
        if match := re.search(
            r"await\s+[a-zA-Z0-9_$]+\.paint\s*\(([a-zA-Z0-9_$]+),\s*[a-zA-Z0-9_$]+\)",
            file.read_text(encoding="utf-8"),
        ):
            arg1 = match.group(1)
            break
    else:
        raise ShoudQuit("paint function object not found")
    logger.debug(f"Found paint function in chunk: {file.name}")

    pattern = r"return[a-zA-Z0-9_$\(\)\s\.]+\.visitorId"
    match = re.search(pattern, content)
    if match is None:
        raise ShoudQuit("fingerprint retrieval statement not found")
    logger.debug("Modifying fingerprint retrieval to use provided fingerprint")
    content = re.sub(pattern, f"return '{fp}'", content)

    pattern = r"const " + re.escape(arg1) + r"\s*=\s*\[...([a-zA-Z0-9_$]+)\.values\(\)\];"
    match = re.search(pattern, content)
    if match is None:
        raise ShoudQuit("array source for paint function argument not found")
    pixels_map_var = match.group(1)
    logger.debug(f"Array source for paint function argument found: {pixels_map_var}")

    pattern = r"const\s+" + re.escape(pixels_map_var) + r"\s*=\s*new\s+Map\b[a-zA-Z0-9_$,=\s]*;"
    match = re.search(pattern, content)
    if match is None:
        raise ShoudQuit("pixels map definition not found")
    stmt = match.group(0)
    logger.debug(f"Pixels map definition statement found: {stmt[:60]}...")

    modified_content = "export const XX_EXPORT={};" + content.replace(stmt, f"{stmt}XX_EXPORT.m={pixels_map_var};")
    chunk_name = file.relative_to(CHUNKS_DIR.resolve()).as_posix()
    chunk_url = f"https://wplace.live/_app/immutable/{chunk_name}"
    return chunk_url, modified_content
