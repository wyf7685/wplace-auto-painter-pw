import io
from typing import Protocol

import anyio
import bot7685_ext.wplace
import httpx
from bot7685_ext.wplace import ColorEntry, compose_tiles

from .config import Config, TemplateConfig
from .log import logger
from .utils import (
    PerfLog,
    WplacePixelCoords,
    parse_rgb_str,
    with_retry,
    with_semaphore,
)

type RGBA = tuple[int, int, int, int]


class PixelAccess[TPixel](Protocol):
    def __getitem__(self, xy: tuple[int, int]) -> TPixel: ...
    def __setitem__(self, xy: tuple[int, int], color: TPixel) -> None: ...


logger = logger.opt(colors=True)


@PerfLog.for_method()
async def download_preview(
    coord1: WplacePixelCoords,
    coord2: WplacePixelCoords,
    background: str | None = None,
) -> bytes:
    coord1, coord2 = coord1.fix_with(coord2)
    tile_imgs: dict[tuple[int, int], bytes] = {}
    logger.info(f"Downloading preview from <y>{coord1.human_repr()}</> to <y>{coord2.human_repr()}</>")

    @with_semaphore(4)
    @with_retry(
        *(httpx.ConnectError, httpx.TimeoutException, httpx.HTTPStatusError),
        delay=1,
    )
    async def fetch_tile(x: int, y: int) -> None:
        resp = await client.get(f"https://backend.wplace.live/files/s0/tiles/{x}/{y}.png")
        tile_imgs[(x, y)] = resp.raise_for_status().read()

    async with (
        PerfLog.for_action("downloading tiles") as perf,
        httpx.AsyncClient(proxy=Config.load().proxy) as client,
        anyio.create_task_group() as tg,
    ):
        for x, y in coord1.all_tile_coords(coord2):
            tg.start_soon(fetch_tile, x, y)
    logger.info(f"Downloaded <g>{len(tile_imgs)}</> tiles (<y>{perf.elapsed:.2f}</>s)")

    with PerfLog.for_action("creating image") as perf:
        image = await compose_tiles(
            [*tile_imgs.items()],
            coord1.tuple(),
            coord2.tuple(),
            parse_rgb_str(background) if background else None,
        )
    logger.info(f"Created image in <y>{perf.elapsed:.2f}</>s")
    return image


@PerfLog.for_method()
async def calc_template_diff(
    cfg: TemplateConfig,
    *,
    include_pixels: bool = False,
) -> list[ColorEntry]:
    template_img = cfg.load_im()
    coords = cfg.get_coords()
    with io.BytesIO() as buffer:
        template_img.save(buffer, format="PNG")
        template_bytes = buffer.getvalue()
    actual_bytes = await download_preview(*coords)

    with PerfLog.for_action("calculating template diff") as perf:
        diff = await bot7685_ext.wplace.compare(template_bytes, actual_bytes, include_pixels)
    logger.info(f"Calculated template diff in <y>{perf.elapsed:.3f}</>s")
    logger.info(f"Template diff count: <y>{sum(e.count for e in diff)}</> pixels")

    return diff
