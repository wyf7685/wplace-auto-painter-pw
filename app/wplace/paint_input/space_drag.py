from collections.abc import Iterable
from typing import TYPE_CHECKING

from .common import SPACE_DRAG_MAX_RADIUS, Pixel, paint_strokes

if TYPE_CHECKING:
    from app.utils.func import LoggerWrapper
    from app.wplace.page import WplacePage
    from app.wplace.page.panel import PaintPanel


def plan_space_drag_strokes(pixels: Iterable[Pixel], max_radius: int = SPACE_DRAG_MAX_RADIUS) -> list[list[Pixel]]:
    if max_radius <= 0:
        raise ValueError("max_radius must be greater than 0")

    strokes: list[list[Pixel]] = []
    current: list[Pixel] = []
    for pixel in pixels:
        if current:
            previous = current[-1]
            anchor = current[0]
            is_adjacent = max(abs(pixel.x - previous.x), abs(pixel.y - previous.y)) <= 1
            is_within_radius = max(abs(pixel.x - anchor.x), abs(pixel.y - anchor.y)) <= max_radius
            if pixel.color != previous.color or not is_adjacent or not is_within_radius:
                strokes.append(current)
                current = []
        current.append(pixel)

    if current:
        strokes.append(current)
    return strokes


async def paint_pixels(pixels: list[Pixel], page: WplacePage, paint: PaintPanel, log: LoggerWrapper) -> None:
    await paint_strokes(plan_space_drag_strokes(pixels), pixels[0], page, paint, log)
