import functools
import json
import re
from collections.abc import Iterable
from pathlib import Path

import anyio
import anyio.to_thread
import ayafileio
import cloudscraper
import httpx

from app.config import Config
from app.const import DATA_DIR
from app.exception import ResolveFailed
from app.log import escape_tag, logger
from app.utils import requests_proxies, with_retry, with_semaphore

CHUNKS_DIR = DATA_DIR / "js_chunks"
CHUNK_ETAG_FILE = CHUNKS_DIR / "etag.json"


async def load_chunk_etags() -> dict[str, str]:
    if not CHUNK_ETAG_FILE.exists():
        return {}

    async with ayafileio.open(CHUNK_ETAG_FILE, "r", encoding="utf-8") as file:
        content = await file.read()
    return json.loads(content)


async def save_chunk_etags(etags: dict[str, str]) -> None:
    async with ayafileio.open(CHUNK_ETAG_FILE, "w", encoding="utf-8") as file:
        await file.write(json.dumps(etags))


class Chunks:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self._cached: dict[str, str] = {}

    def read(self, chunk_path: str) -> str:
        if chunk_path in self._cached:
            return self._cached[chunk_path]

        file = self.root / chunk_path
        content = file.read_text(encoding="utf-8")
        self._cached[chunk_path] = content
        return content

    def iter_chunks(self) -> Iterable[tuple[str, str]]:
        for file in self.root.glob("*/*.js"):
            chunk_path = file.relative_to(self.root).as_posix()
            yield chunk_path, self.read(chunk_path)

    def path(self, chunk_path: str) -> Path:
        return self.root / chunk_path

    def url(self, chunk_path: str) -> str:
        return f"https://wplace.live/_app/immutable/{chunk_path}"


PATTERN_CHUNK_NAME = re.compile(r"_app/immutable/(?P<path>.+?)\.js")


async def find_chunk_names() -> set[str]:
    logger.debug("Preparing JS chunks...")
    resp = await anyio.to_thread.run_sync(
        functools.partial(
            cloudscraper.create_scraper().get,
            url="https://wplace.live/",
            proxies=requests_proxies(),
        )
    )
    resp.raise_for_status()
    chunks = {f"{match.group('path')}.js" for match in PATTERN_CHUNK_NAME.finditer(resp.text)}
    logger.opt(colors=True).debug(f"Found <y>{len(chunks)}</> JS chunks")
    return chunks


async def prepare_chunks(chunk_names: set[str]) -> Chunks:
    CHUNKS_DIR.mkdir(parents=True, exist_ok=True)
    etags = await load_chunk_etags()
    for chunk_name in set(etags.keys()) - chunk_names:
        # Remove obsolete chunks
        del etags[chunk_name]
        CHUNKS_DIR.joinpath(chunk_name).unlink(missing_ok=True)

    downloaded = 0

    @with_retry(httpx.RequestError, retries=3, delay=1)
    @with_semaphore(16)
    async def download_js_chunk(chunk_name: str) -> None:
        nonlocal downloaded

        chunk_path = CHUNKS_DIR / chunk_name
        chunk_path.parent.mkdir(parents=True, exist_ok=True)

        headers = (
            {"If-None-Match": etags[chunk_name]}
            if chunk_name in etags and chunk_path.exists() and chunk_path.stat().st_size > 0
            else {}
        )
        url = f"https://wplace.live/_app/immutable/{chunk_name}"
        async with client.stream("GET", url, headers=headers) as response:
            if response.status_code == 304:
                return  # Not modified
            response.raise_for_status()
            if etag := response.headers.get("ETag"):
                etags[chunk_name] = etag
            logger.opt(colors=True).debug(f"Downloading JS chunk: <i><c>{escape_tag(chunk_name)}</></>")
            async with ayafileio.open(chunk_path, "wb") as file:
                async for chunk in response.aiter_bytes(1024 * 1024):
                    await file.write(chunk)
            downloaded += 1

    async with (
        httpx.AsyncClient(proxy=Config.load().proxy, timeout=30) as client,
        anyio.create_task_group() as tg,
    ):
        for chunk_name in chunk_names:
            tg.start_soon(download_js_chunk, chunk_name)

    await save_chunk_etags(etags)
    logger.opt(colors=True).debug(
        f"Prepared JS chunks, <y>{downloaded}</> downloaded, <y>{len(chunk_names) - downloaded}</> cached"
    )

    return Chunks(CHUNKS_DIR)


PATTERN_PAINT_FN = re.compile(r"await\s+(?P<name>[a-zA-Z0-9_$]+)\.paint\s*\(")


def find_paint_fn(chunks: Chunks) -> tuple[str, str]:
    for chunk_path, content in chunks.iter_chunks():  # noqa: B007
        if match := PATTERN_PAINT_FN.search(content):
            obj_name = match.group("name")
            break
    else:
        raise ResolveFailed("paint function object not found")

    pattern = (
        r"import\s*\{[^}]*?\b(?P<source>[a-zA-Z0-9_$]+)\s+as\s+"
        + re.escape(obj_name)
        + r"[^}]*?\}\s*from\s*[\"'](?P<chunk>[^\"']+)[\"'];"
    )
    match = re.search(pattern, content)
    if match is None:
        raise ResolveFailed("import source for paint function object not found")

    source_name = match.group("source")
    source_chunk = match.group("chunk")
    source_chunk_path = (
        chunks.path(chunk_path).parent.joinpath(source_chunk).resolve().relative_to(chunks.root).as_posix()
    )

    return source_name, chunks.url(source_chunk_path)


PATTERN_WORKER = re.compile(
    r"function (?P<name>[a-zA-Z0-9_$]+)\([a-zA-Z0-9_$]+\)\{const [a-zA-Z0-9_$]+=Math.random\(\)"
)


def find_worker_fn(chunks: Chunks) -> tuple[str, str]:
    for chunk_path, content in chunks.iter_chunks():  # noqa: B007
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

    return export_name, chunks.url(chunk_path)


PATTERN_SEASON_NUM_ASSIGN = re.compile(r",(?P<name>[a-zA-Z0-9_$]+)=[a-zA-Z0-9_$]+.seasons.length-1")


def find_season_num(chunks: Chunks) -> tuple[str, str]:
    for chunk_path, content in chunks.iter_chunks():  # noqa: B007
        if match := PATTERN_SEASON_NUM_ASSIGN.search(content):
            obj_name = match.group("name")
            break
    else:
        raise ResolveFailed("season number assignment not found")

    pattern = r"export\s*\{[^}]*?\b,?" + re.escape(obj_name) + r"(?:\s+as\s+(?P<name>[a-zA-Z0-9_$]+))?[^}]*?\};"
    match = re.search(pattern, content)
    if match is None:
        raise ResolveFailed("exported name for season number not found")
    export_name = match.group("name") or obj_name

    return export_name, chunks.url(chunk_path)


PATTERN_PATCHES_MAP = re.compile(
    r",\s*(?P<name>[a-zA-Z0-9_$]+)\s*=\s*Object.assign\(\{(?P<quote>['\"])\./markdown/.+(?P=quote):\s*[a-zA-Z0-9_$]+,"
)


def find_patch_logs(chunks: Chunks) -> tuple[str, str]:
    for chunk_path, content in chunks.iter_chunks():  # noqa: B007
        if match := PATTERN_PATCHES_MAP.search(content):
            patches_map_name = match.group("name")
            break
    else:
        raise ResolveFailed("patches map not found")

    pattern = r",\s*(?P<name>[a-zA-Z0-9_$]+)\s*=\s*Object\.entries\(\s*" + re.escape(patches_map_name) + r"\s*\)\.map\("
    match = re.search(pattern, content)
    if match is None:
        raise ResolveFailed("patches array not found")
    array_name = match.group("name")

    pattern = r"export\s*\{[^}]*?\b,?" + re.escape(array_name) + r"(?:\s+as\s+(?P<name>[a-zA-Z0-9_$]+))?[^}]*?\};"
    match = re.search(pattern, content)
    if match is None:
        raise ResolveFailed("exported name for patches array not found")
    export_name = match.group("name") or array_name

    return export_name, chunks.url(chunk_path)


_resolve_cache: tuple[set[str], list[tuple[str, str]]] | None = None
_resolvers = find_paint_fn, find_worker_fn, find_season_num, find_patch_logs


@with_semaphore(1)
async def resolve_js() -> list[tuple[str, str]]:
    global _resolve_cache
    chunk_names = await find_chunk_names()
    if _resolve_cache is not None and _resolve_cache[0] == chunk_names:
        logger.debug("Using cached JS resolution")
        return _resolve_cache[1]
    chunks = await prepare_chunks(chunk_names)
    result = [fn(chunks) for fn in _resolvers]
    _resolve_cache = (chunk_names, result)
    return result
