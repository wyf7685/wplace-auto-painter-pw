import io
import math
from collections import deque
from typing import Protocol

import bot7685_ext.wplace
from bot7685_ext.wplace import ColorEntry

from .config import TemplateConfig
from .log import logger
from .preview import download_preview
from .utils import PerfLog

type RGBA = tuple[int, int, int, int]


class PixelAccess[TPixel](Protocol):
    def __getitem__(self, xy: tuple[int, int]) -> TPixel: ...
    def __setitem__(self, xy: tuple[int, int], color: TPixel) -> None: ...


logger = logger.opt(colors=True)


async def download_template_preview(
    cfg: TemplateConfig,
    background: str | None = None,
    border_pixels: int = 0,
) -> bytes:
    coord1, coord2 = cfg.get_coords()
    if border_pixels > 0:
        coord1 = coord1.offset(-border_pixels, -border_pixels)
        coord2 = coord2.offset(border_pixels, border_pixels)
    return await download_preview(coord1, coord2, background)


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


def group_adjacent(
    points: list[tuple[int, int, int]],
    min_group_size: int = 100,
    merge_distance: float = 50.0,
) -> list[list[tuple[int, int, int]]]:
    # 将点放入集合以便 O(1) 查找
    point_dict: dict[tuple[int, int], int] = {(x, y): color_id for x, y, color_id in points}
    visited: set[tuple[int, int]] = set()
    groups: list[list[tuple[int, int, int]]] = []

    # 8 邻域方向
    directions = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]

    def bfs(start: tuple[int, int, int]) -> None:
        """从起点开始 BFS 找出一个连通分组"""
        q = deque([start[:2]])
        group = [start]
        visited.add(start[:2])

        while q:
            x, y = q.popleft()
            for dx, dy in directions:
                neighbor = x + dx, y + dy
                if neighbor in point_dict and neighbor not in visited:
                    visited.add(neighbor)
                    q.append(neighbor)
                    group.append((*neighbor, point_dict[neighbor]))

        groups.append(group)

    # 遍历所有点
    for p in points:
        if p not in visited:
            bfs(p)

    # 根据距离合并相邻的小分组
    merged = True
    while merged:
        merged = False
        for i in range(len(groups)):
            for j in range(i + 1, len(groups)):
                if calc_group_distance_centroid(groups[i], groups[j]) <= merge_distance:
                    groups[i].extend(groups[j])
                    groups.pop(j)
                    merged = True
                    break
            if merged:
                break

    # 根据大小继续合并
    small_groups = [g for g in groups if len(g) < min_group_size]
    large_groups = [g for g in groups if len(g) >= min_group_size]
    for small in small_groups:
        if not large_groups:
            large_groups.append(small)
            continue
        closest_large = min(
            large_groups,
            key=lambda lg: calc_group_distance_centroid(small, lg),
        )
        closest_large.extend(small)

    return sorted(groups, key=len, reverse=True)


def calc_group_distance_centroid(
    group1: list[tuple[int, int, int]],
    group2: list[tuple[int, int, int]],
) -> float:
    cx1 = sum(x for x, _, _ in group1) / len(group1)
    cy1 = sum(y for _, y, _ in group2) / len(group1)
    cx2 = sum(x for x, _, _ in group2) / len(group2)
    cy2 = sum(y for _, y, _ in group2) / len(group2)
    return math.sqrt((cx1 - cx2) ** 2 + (cy1 - cy2) ** 2)
