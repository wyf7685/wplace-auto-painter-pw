import json
import re
import time
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING, cast

import anyio
import ayafileio
import httpx

from app.browser import get_browser
from app.config import Config
from app.const import DATA_DIR
from app.exception import ResolveFailed
from app.log import escape_tag, logger
from app.utils import with_retry, with_semaphore

if TYPE_CHECKING:
    from playwright.async_api import Page

CHUNKS_DIR = DATA_DIR / "js_chunks"
CHUNK_ETAG_FILE = CHUNKS_DIR / "etag.json"
# Chunk URLs are content-hashed; avoid browser startup on every painting cycle.
JS_RESOLUTION_CACHE_TTL = 60 * 60


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


CHUNK_DISCOVERY_SCRIPT = r"""(async () => {
    const immutablePrefix = "/_app/immutable/";
    const dependencyPattern = /(?:\.\.\/|\.\/)(?:chunks|nodes|entry)\/[A-Za-z0-9._-]+\.js/g;
    const scripts = new Set();
    const pendingNodes = [];
    const visitedNodes = new Set();

    const normalize = url => {
        const parsed = new URL(url, location.href);
        if (parsed.origin !== location.origin || !parsed.pathname.startsWith(immutablePrefix)) {
            return null;
        }

        const path = parsed.pathname.slice(immutablePrefix.length);
        return /^(?:chunks|nodes|entry)\/[^/]+\.js$/.test(path) ? path : null;
    };

    const addScript = url => {
        const path = normalize(url);
        if (path === null || scripts.has(path)) {
            return;
        }

        scripts.add(path);
        if (path.startsWith("nodes/") && !visitedNodes.has(path)) {
            pendingNodes.push(path);
        }
    };

    for (const link of document.querySelectorAll('head link[rel="modulepreload"]')) {
        addScript(link.href);
    }

    while (pendingNodes.length > 0) {
        const nodePath = pendingNodes.shift();
        if (visitedNodes.has(nodePath)) {
            continue;
        }
        visitedNodes.add(nodePath);

        const nodeUrl = new URL(immutablePrefix + nodePath, location.origin);
        const response = await fetch(nodeUrl, {credentials: "same-origin"});
        if (!response.ok) {
            throw new Error(`Failed to read ${nodeUrl}: ${response.status}`);
        }

        const source = await response.text();
        for (const match of source.matchAll(dependencyPattern)) {
            addScript(new URL(match[0], nodeUrl).href);
        }
    }

    return [...scripts];
})()"""


async def _extract_chunk_names(page: Page) -> set[str]:
    chunk_names = cast("list[str]", await page.evaluate(CHUNK_DISCOVERY_SCRIPT))
    return set(chunk_names)


async def find_chunk_names() -> set[str]:
    logger.debug("Discovering JS chunks from the browser dependency graph...")
    async with (
        get_browser(headless=True) as browser,
        await browser.new_context() as context,
        await context.new_page() as page,
    ):
        await page.goto("https://wplace.live/", wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_load_state("load", timeout=60_000)
        await page.wait_for_selector('head link[rel="modulepreload"]', state="attached", timeout=30_000)
        chunks = await _extract_chunk_names(page)

    if not chunks:
        raise ResolveFailed("no JS chunks found in browser dependency graph")

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
        temp_path = chunk_path.with_name(f".{chunk_path.name}.tmp")

        try:
            async with client.stream("GET", url, headers=headers) as response:
                if response.status_code == 304:
                    return  # Not modified
                response.raise_for_status()
                logger.opt(colors=True).debug(f"Downloading JS chunk: <i><c>{escape_tag(chunk_name)}</></>")
                async with ayafileio.open(temp_path, "wb") as file:
                    async for chunk in response.aiter_bytes(1024 * 1024):
                        await file.write(chunk)

            temp_path.replace(chunk_path)
            if etag := response.headers.get("ETag"):
                etags[chunk_name] = etag
            else:
                etags.pop(chunk_name, None)
            downloaded += 1
        finally:
            temp_path.unlink(missing_ok=True)

    try:
        async with (
            httpx.AsyncClient(proxy=Config.load().proxy, timeout=30) as client,
            anyio.create_task_group() as tg,
        ):
            for chunk_name in chunk_names:
                tg.start_soon(download_js_chunk, chunk_name)
    finally:
        # Persist whatever completed: losing the whole ledger to one failed chunk
        # would force a full re-download on the next cycle.
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


PATTERN_WORKER_FN = re.compile(
    r"(?:async\s+)?function\s+(?P<name>[a-zA-Z0-9_$]+)\((?P<arg>[a-zA-Z0-9_$]+)\)\s*\{\s*"
    r"(?:return|await)\s+[a-zA-Z0-9_$]+\(\{\s*type:\s*(?P<quote>['\"`])paintPixels(?P=quote),"
    r"\s*data:\s*(?P=arg)\s*\}\)"
)


PATTERN_EXPORT_BLOCK = re.compile(r"export\s*\{(?P<entries>[^}]*)\};")
PATTERN_EXPORT_ENTRY = re.compile(r"(?P<local>[a-zA-Z0-9_$]+)(?:\s+as\s+(?P<exported>[a-zA-Z0-9_$]+))?")


def _find_exported_name(content: str, local_name: str) -> str | None:
    for block_match in PATTERN_EXPORT_BLOCK.finditer(content):
        for entry in block_match.group("entries").split(","):
            entry_match = PATTERN_EXPORT_ENTRY.fullmatch(entry.strip())
            if entry_match is not None and entry_match.group("local") == local_name:
                return entry_match.group("exported") or local_name
    return None


def find_worker_fn(chunks: Chunks) -> tuple[str, str]:
    for chunk_path, content in chunks.iter_chunks():  # noqa: B007
        if match := PATTERN_WORKER_FN.search(content):
            wrapper_name = match.group("name")
            break
    else:
        raise ResolveFailed("service worker wrapper not found")

    export_name = _find_exported_name(content, wrapper_name)
    if export_name is None:
        raise ResolveFailed("exported name for wrapper not found")

    return export_name, chunks.url(chunk_path)


PATTERN_SEASON_NUM_ASSIGN = re.compile(r",(?P<name>[a-zA-Z0-9_$]+)=[a-zA-Z0-9_$]+.seasons.length-1")


def find_season_num(chunks: Chunks) -> tuple[str, str]:
    for chunk_path, content in chunks.iter_chunks():  # noqa: B007
        if match := PATTERN_SEASON_NUM_ASSIGN.search(content):
            obj_name = match.group("name")
            break
    else:
        raise ResolveFailed("season number assignment not found")

    export_name = _find_exported_name(content, obj_name)
    if export_name is None:
        raise ResolveFailed("exported name for season number not found")

    return export_name, chunks.url(chunk_path)


PATTERN_PATCHES_MAP = re.compile(
    r",\s*(?P<name>[a-zA-Z0-9_$]+)\s*=\s*Object.assign\(\{(?P<quote>['\"`])\./markdown/.+(?P=quote):\s*[a-zA-Z0-9_$]+,"
)
PATTERN_PATCHES_DIRECT = re.compile(
    r",\s*(?P<name>[a-zA-Z0-9_$]+)\s*=\s*Object\.entries\(\s*Object\.assign\(\{(?P<quote>['\"`])\./markdown/.+(?P=quote):\s*[a-zA-Z0-9_$]+,"
)


def find_patch_logs(chunks: Chunks) -> tuple[str, str]:
    array_name: str | None = None
    patches_map_name: str | None = None
    for chunk_path, content in chunks.iter_chunks():  # noqa: B007
        if match := PATTERN_PATCHES_DIRECT.search(content):
            array_name = match.group("name")
            break
        if match := PATTERN_PATCHES_MAP.search(content):
            patches_map_name = match.group("name")
            break
    else:
        raise ResolveFailed("patches source not found")

    if array_name is None:
        if patches_map_name is None:
            raise ResolveFailed("patches map not found")
        pattern = (
            r",\s*(?P<name>[a-zA-Z0-9_$]+)\s*=\s*Object\.entries\(\s*" + re.escape(patches_map_name) + r"\s*\)\.map\("
        )
        match = re.search(pattern, content)
        if match is None:
            raise ResolveFailed("patches array not found")
        array_name = match.group("name")

    assert array_name is not None
    export_name = _find_exported_name(content, array_name)
    if export_name is None:
        raise ResolveFailed("exported name for patches array not found")

    return export_name, chunks.url(chunk_path)


_resolve_cache: tuple[float, list[tuple[str, str]]] | None = None
_resolvers = find_paint_fn, find_worker_fn, find_season_num, find_patch_logs


@with_semaphore(1)
async def resolve_js() -> list[tuple[str, str]]:
    global _resolve_cache
    now = time.monotonic()
    if _resolve_cache is not None and now - _resolve_cache[0] < JS_RESOLUTION_CACHE_TTL:
        logger.debug("Using cached JS resolution")
        return _resolve_cache[1]

    chunk_names = await find_chunk_names()
    chunks = await prepare_chunks(chunk_names)
    result = [fn(chunks) for fn in _resolvers]
    _resolve_cache = (time.monotonic(), result)
    return result
