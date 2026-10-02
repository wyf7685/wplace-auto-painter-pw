import random
from collections.abc import Iterable
from typing import TYPE_CHECKING, NamedTuple

import anyio
from bot7685_ext.wplace.consts import COLORS_NAME

if TYPE_CHECKING:
    from app.utils.func import LoggerWrapper
    from app.wplace.page import WplacePage
    from app.wplace.page.panel import PaintPanel

SPACE_DRAG_MAX_RADIUS = 20


class Pixel(NamedTuple):
    x: int
    y: int
    color: int


async def switch_color(paint: PaintPanel, previous: int, current: int, log: LoggerWrapper) -> None:
    if previous == current:
        return
    await anyio.sleep(random.uniform(0.5, 1.5))
    log.info(
        f"Switching color: <g>{COLORS_NAME[previous]}</>(id=<c>{previous}</>) "
        f"-> <g>{COLORS_NAME[current]}</>(id=<c>{current}</>)"
    )
    await paint.select_color(current)
    await anyio.sleep(random.uniform(0.5, 1.5))


async def take_short_break(log: LoggerWrapper) -> None:
    if random.random() < 0.02:
        idle_secs = random.uniform(0.5, 2.0)
        log.debug(f"Taking a short break for <y>{idle_secs:.2f}</> seconds...")
        await anyio.sleep(idle_secs)


async def paint_strokes(
    strokes: Iterable[list[Pixel]],
    anchor: Pixel,
    page: WplacePage,
    paint: PaintPanel,
    log: LoggerWrapper,
) -> None:
    previous_color = anchor.color
    for stroke in strokes:
        first = stroke[0]
        await switch_color(paint, previous_color, first.color, log)
        await page.move_by_pixel(first.x - anchor.x, first.y - anchor.y)
        anchor = first
        await page.paint_space_drag([(pixel.x - anchor.x, pixel.y - anchor.y) for pixel in stroke])
        previous_color = first.color
        await take_short_break(log)
