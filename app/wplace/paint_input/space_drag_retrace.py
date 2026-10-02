from collections import deque
from collections.abc import Iterable
from typing import TYPE_CHECKING

import anyio.to_thread

from .common import SPACE_DRAG_MAX_RADIUS, Pixel, paint_strokes

if TYPE_CHECKING:
    from app.utils.func import LoggerWrapper
    from app.wplace.page import WplacePage
    from app.wplace.page.panel import PaintPanel

_SPACE_DRAG_NEIGHBORS = tuple((dx, dy) for dy in (-1, 0, 1) for dx in (-1, 0, 1) if dx or dy)

type _PixelPosition = tuple[int, int]


def _next_space_drag_target(
    start: _PixelPosition,
    anchor: _PixelPosition,
    pending: set[_PixelPosition],
    positions: dict[_PixelPosition, Pixel],
    rank: dict[_PixelPosition, int],
    max_radius: int,
) -> list[_PixelPosition]:
    queue = deque([start])
    parents = {start: start}
    while queue:
        current = queue.popleft()
        candidates = ((current[0] + dx, current[1] + dy) for dx, dy in _SPACE_DRAG_NEIGHBORS)
        adjacent = sorted(
            (
                point
                for point in candidates
                if point in positions
                and point not in parents
                and max(abs(point[0] - anchor[0]), abs(point[1] - anchor[1])) <= max_radius
            ),
            key=rank.__getitem__,
        )
        for point in adjacent:
            parents[point] = current
            if point in pending:
                path = [point]
                while path[-1] != start:
                    path.append(parents[path[-1]])
                path.reverse()
                return path[1:]
            queue.append(point)
    return []


def plan_space_drag_strokes(pixels: Iterable[Pixel], max_radius: int = SPACE_DRAG_MAX_RADIUS) -> list[list[Pixel]]:
    """Cover same-color targets within each anchor window, retracing covered pixels.

    Strokes are pointer paths and can repeat pixels. Use the original targets,
    not these paths, for charge accounting and submission.
    """
    if max_radius <= 0:
        raise ValueError("max_radius must be greater than 0")
    colors: dict[int, dict[_PixelPosition, Pixel]] = {}
    for pixel in pixels:
        colors.setdefault(pixel.color, {})[(pixel.x, pixel.y)] = pixel

    strokes: list[list[Pixel]] = []
    for positions in colors.values():
        pending = set(positions)
        rank = {point: index for index, point in enumerate(positions)}
        for anchor in positions:
            if anchor not in pending:
                continue
            pending.remove(anchor)
            stroke = [anchor]
            while pending:
                extension = _next_space_drag_target(stroke[-1], anchor, pending, positions, rank, max_radius)
                if not extension:
                    break
                stroke.extend(extension)
                pending.remove(extension[-1])
            strokes.append([positions[point] for point in stroke])
    return strokes


async def paint_pixels(pixels: list[Pixel], page: WplacePage, paint: PaintPanel, log: LoggerWrapper) -> None:
    strokes = await anyio.to_thread.run_sync(plan_space_drag_strokes, pixels)
    await paint_strokes(strokes, pixels[0], page, paint, log)
