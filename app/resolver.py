import functools
import hashlib
import json
import re
from typing import Any

import anyio
import anyio.to_thread
import cloudscraper
import httpx

from app.log import escape_tag, logger

from .config import DATA_DIR, Config
from .exception import ShoudQuit
from .utils import requests_proxies, with_semaphore

PATTERN_CHUNK_NAME = re.compile(r"_app/immutable/(.+?)\.js")
PATTERN_FP_STMT = re.compile(r"return[a-zA-Z0-9_$\(\)\s\.]+\.visitorId")
CHUNKS_DIR = DATA_DIR / "js_chunks"
CHUNK_ETAG_FILE = CHUNKS_DIR / "etag.json"

CHUNK_RESOLVE_CACHE = CHUNKS_DIR / "resolve_cache.json"
CHUNK_RESOLVE_CACHE_VERSION = 1
type ChunkResolveCache = list[str]  # chunk_url, modified_content


def load_chunk_etags() -> dict[str, str]:
    if not CHUNK_ETAG_FILE.exists():
        return {}

    return json.loads(CHUNK_ETAG_FILE.read_text(encoding="utf-8"))


def save_chunk_etags(etags: dict[str, str]) -> None:
    CHUNK_ETAG_FILE.write_text(json.dumps(etags), encoding="utf-8")


def calc_etag_hash(etags: dict[str, str]) -> str:
    etag_str = "\n".join(f"{k}|{v}" for k, v in sorted(etags.items()))
    return hashlib.sha256(etag_str.encode("utf-8")).hexdigest()


def load_resolve_cache() -> ChunkResolveCache | None:
    if not CHUNK_RESOLVE_CACHE.exists():
        return None

    data: dict[str, Any] = json.loads(CHUNK_RESOLVE_CACHE.read_text(encoding="utf-8"))
    if data.get("version") != CHUNK_RESOLVE_CACHE_VERSION:
        return None

    return data.get("cache", {})


def save_resolve_cache(cache: ChunkResolveCache) -> None:
    data = {"version": CHUNK_RESOLVE_CACHE_VERSION, "cache": cache}
    CHUNK_RESOLVE_CACHE.write_text(json.dumps(data), encoding="utf-8")


@with_semaphore(1)
async def prepare_chunks() -> bool:
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
    old_hash = calc_etag_hash(etags)
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

    new_hash = calc_etag_hash(etags)
    save_chunk_etags(etags)
    return new_hash == old_hash  # cache hit


async def resolve_pixel_map(fp: str) -> tuple[str, str]:  # chunk_url, modified_content
    fp_placeholder = "{{XX_FP_PLACEHOLDER}}"

    cache_hit = await prepare_chunks()
    if cache_hit and (cache := load_resolve_cache()) is not None:
        chunk_url, modified_content = cache[:2]
        modified_content = modified_content.replace(fp_placeholder, fp)
        logger.debug("Using cached chunk resolution")
        return chunk_url, modified_content

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

    match = PATTERN_FP_STMT.search(content)
    if match is None:
        raise ShoudQuit("fingerprint retrieval statement not found")
    logger.debug("Modifying fingerprint retrieval to use provided fingerprint")

    modified_content = "export const XX_EXPORT={};" + PATTERN_FP_STMT.sub(
        f"return '{fp_placeholder}'", content
    ).replace(stmt, f"{stmt}XX_EXPORT.m={pixels_map_var};")

    chunk_name = file.relative_to(CHUNKS_DIR.resolve()).as_posix()
    chunk_url = f"https://wplace.live/_app/immutable/{chunk_name}"

    save_resolve_cache([chunk_url, modified_content])
    return chunk_url, modified_content.replace(fp_placeholder, fp)
