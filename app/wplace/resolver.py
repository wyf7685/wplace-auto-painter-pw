import functools
import json
import re

import anyio
import anyio.to_thread
import cloudscraper
import httpx

from app.config import Config
from app.const import DATA_DIR
from app.exception import ResolveFailed
from app.log import escape_tag, logger
from app.utils import requests_proxies, with_semaphore

CHUNKS_DIR = DATA_DIR / "js_chunks"
CHUNK_ETAG_FILE = CHUNKS_DIR / "etag.json"


def load_chunk_etags() -> dict[str, str]:
    if not CHUNK_ETAG_FILE.exists():
        return {}

    return json.loads(CHUNK_ETAG_FILE.read_text(encoding="utf-8"))


def save_chunk_etags(etags: dict[str, str]) -> None:
    CHUNK_ETAG_FILE.write_text(json.dumps(etags), encoding="utf-8")


PATTERN_CHUNK_NAME = re.compile(r"_app/immutable/(?P<path>.+?)\.js")


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

    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    chunks = {f"{match.group('path')}.js" for match in PATTERN_CHUNK_NAME.finditer(resp.text)}
    etags = load_chunk_etags()
    for chunk_name in set(etags.keys()) - chunks:
        # Remove obsolete chunks
        del etags[chunk_name]
        CHUNKS_DIR.joinpath(chunk_name).unlink(missing_ok=True)

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

    async with httpx.AsyncClient(proxy=Config.load().proxy, timeout=30) as client, anyio.create_task_group() as tg:
        for chunk_name in chunks:
            tg.start_soon(download_js_chunk, chunk_name)

    save_chunk_etags(etags)


PATTERN_PAINT_FN = re.compile(r"await\s+(?P<name>[a-zA-Z0-9_$]+)\.paint\s*\(")


def find_paint_fn() -> tuple[str, str]:
    for file in CHUNKS_DIR.joinpath("nodes").glob("*.js"):
        if match := PATTERN_PAINT_FN.search(file.read_text(encoding="utf-8")):
            obj_name = match.group("name")
            break
    else:
        raise ResolveFailed("paint function object not found")

    pattern = (
        r"import\s*\{[^}]*?\b(?P<source>[a-zA-Z0-9_$]+)\s+as\s+"
        + re.escape(obj_name)
        + r"[^}]*?\}\s*from\s*[\"'](?P<chunk>[^\"']+)[\"'];"
    )
    match = re.search(pattern, file.read_text(encoding="utf-8"))
    if match is None:
        raise ResolveFailed("import source for paint function object not found")

    source_name = match.group("source")
    chunk_name = match.group("chunk")
    chunk_path = file.parent.joinpath(chunk_name).resolve().relative_to(CHUNKS_DIR.resolve()).as_posix()
    chunk_url = f"https://wplace.live/_app/immutable/{chunk_path}"
    return source_name, chunk_url


PATTERN_WORKER = re.compile(r"function (?P<name>[a-zA-Z0-9_$]+)\([a-zA-Z0-9_$]+\)\{const .+=Math.random\(\)")


def find_worker_fn() -> tuple[str, str]:
    for file in CHUNKS_DIR.glob("*/*.js"):
        content = file.read_text("utf-8")
        if ("navigator.serviceWorker.controller" in content) and (match := PATTERN_WORKER.search(content)):
            func_name = match.group("name")
            break
    else:
        raise ResolveFailed("service worker function not found")

    pattern = (
        r"function (?P<name>[a-zA-Z0-9_$]+)\((?P<arg>[a-zA-Z0-9_$]+)\)\s*\{return "
        + re.escape(func_name)
        + r"\(\{type:\s*(?P<quote>['\"])paintPixels(?P=quote),data:\s*(?P=arg)\}\)\}"
    )
    match = re.search(pattern, content)
    if match is None:
        raise ResolveFailed("wrapper function not found")
    wrapper_name = match.group("name")

    pattern = r"export\s*\{[^}]*?\b,?" + re.escape(wrapper_name) + r"(?:\s+as\s+(?P<name>[a-zA-Z0-9_$]+))?[^}]*?\};"
    match = re.search(pattern, content)
    if match is None:
        raise ResolveFailed("exported name for wrapper not found")
    export_name = match.group("name") or wrapper_name

    chunk_path = file.resolve().relative_to(CHUNKS_DIR.resolve()).as_posix()
    chunk_url = f"https://wplace.live/_app/immutable/{chunk_path}"
    return (export_name, chunk_url)


SEASON_NUM_ASSIGN_PATTERN = re.compile(r",(?P<name>[a-zA-Z0-9_$]+)=[a-zA-Z0-9_$]+.seasons.length-1")


def find_season_num() -> tuple[str, str]:
    for file in CHUNKS_DIR.glob("*/*.js"):
        content = file.read_text("utf-8")
        if match := SEASON_NUM_ASSIGN_PATTERN.search(content):
            obj_name = match.group("name")
            break
    else:
        raise ResolveFailed("season number assignment not found")

    pattern = r"export\s*\{[^}]*?\b,?" + re.escape(obj_name) + r"(?:\s+as\s+(?P<name>[a-zA-Z0-9_$]+))?[^}]*?\};"
    match = re.search(pattern, content)
    if match is None:
        raise ResolveFailed("exported name for season number not found")
    export_name = match.group("name") or obj_name

    chunk_path = file.resolve().relative_to(CHUNKS_DIR.resolve()).as_posix()
    chunk_url = f"https://wplace.live/_app/immutable/{chunk_path}"
    return (export_name, chunk_url)


async def resolve_js() -> list[str]:
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    await prepare_chunks()
    return [*find_paint_fn(), *find_worker_fn(), *find_season_num()]
