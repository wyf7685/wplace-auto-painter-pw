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


def load_chunk_etags() -> dict[str, str]:
    if not CHUNK_ETAG_FILE.exists():
        return {}

    return json.loads(CHUNK_ETAG_FILE.read_text(encoding="utf-8"))


def save_chunk_etags(etags: dict[str, str]) -> None:
    CHUNK_ETAG_FILE.write_text(json.dumps(etags), encoding="utf-8")


class JsResolver:
    PATTERN_CHUNK_NAME = re.compile(r"_app/immutable/(.+?)\.js")
    PATTERN_PAINT_FN = re.compile(r"await\s+([a-zA-Z0-9_$]+)\.paint\s*\(")
    PATTERN_WORKER = re.compile(r"function ([a-zA-Z0-9_$]+)\([a-zA-Z0-9_$]+\)\{const .+=Math.random\(\)")

    @with_semaphore(1)
    async def prepare_chunks(self) -> None:
        resp = await anyio.to_thread.run_sync(
            functools.partial(
                cloudscraper.create_scraper().get,
                url="https://wplace.live/",
                proxies=requests_proxies(),
            )
        )
        resp.raise_for_status()

        chunks = {f"{match.group(1)}.js" for match in self.PATTERN_CHUNK_NAME.finditer(resp.text)}
        etags = load_chunk_etags()
        for chunk_name in set(etags.keys()) - chunks:
            # Remove obsolete chunks
            del etags[chunk_name]
            self.chunks_dir.joinpath(chunk_name).unlink(missing_ok=True)

        async def download_js_chunk(chunk_name: str) -> None:
            file = self.chunks_dir / chunk_name
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

    def find_paint_fn(self) -> tuple[str, str]:
        for file in self.chunks_dir.joinpath("nodes").glob("*.js"):
            if match := self.PATTERN_PAINT_FN.search(file.read_text(encoding="utf-8")):
                obj_name = match.group(1)
                break
        else:
            raise ShoudQuit("paint function object not found")

        pattern = (
            r"import\s*\{[^}]*?\b([a-zA-Z0-9_$]+)\s+as\s+"
            + re.escape(obj_name)
            + r"[^}]*?\}\s*from\s*[\"']([^\"']+)[\"'];"
        )
        match = re.search(pattern, file.read_text(encoding="utf-8"))
        if match is None:
            raise ShoudQuit("import source for paint function object not found")

        source_name = match.group(1)
        chunk_name = file.parent.joinpath(match.group(2)).resolve().relative_to(self.chunks_dir.resolve()).as_posix()
        chunk_url = f"https://wplace.live/_app/immutable/{chunk_name}"
        return source_name, chunk_url

    def find_worker_fn(self) -> tuple[str, str]:
        for file in self.chunks_dir.glob("*/*.js"):
            content = file.read_text("utf-8")
            if ("navigator.serviceWorker.controller" in content) and (match := self.PATTERN_WORKER.search(content)):
                func_name = match.group(1)
                break
        else:
            raise ShoudQuit("service worker function not found")

        pattern = (
            r"function ([a-zA-Z0-9_$]+)\([a-zA-Z0-9_$]+\)\s*\{return "
            + re.escape(func_name)
            + r"\(\{type:\s*['\"]paintPixels['\"],data:\s*q\}\)\}"
        )
        match = re.search(pattern, content)
        if match is None:
            raise ShoudQuit("wrapper function not found")
        wrapper_name = match.group(1)

        pattern = r"export\s*\{[^}]*?\b,?" + re.escape(wrapper_name) + r"(?:\s+as\s+([a-zA-Z0-9_$]+))?[^}]*?\};"
        match = re.search(pattern, content)
        if match is None:
            raise ShoudQuit("exported name for wrapper not found")
        export_name = match.group(1) if match.group(1) else wrapper_name

        chunk_name = file.resolve().relative_to(self.chunks_dir.resolve()).as_posix()
        chunk_url = f"https://wplace.live/_app/immutable/{chunk_name}"
        return (export_name, chunk_url)

    async def resolve(self) -> list[str]:
        self.chunks_dir = CHUNKS_DIR
        self.chunks_dir.mkdir(parents=True, exist_ok=True)
        await self.prepare_chunks()
        return [*self.find_paint_fn(), *self.find_worker_fn()]
