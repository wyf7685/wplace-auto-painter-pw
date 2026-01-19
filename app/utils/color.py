import datetime as dt
from collections.abc import Sequence

from bot7685_ext.wplace.consts import ALL_COLORS

UTC8 = dt.timezone(dt.timedelta(hours=8))


def find_color_name(rgba: tuple[int, int, int, int]) -> str:
    if rgba[3] == 0:
        return "Transparent"

    rgb = rgba[:3]
    for name, value in ALL_COLORS.items():
        if value == rgb:
            return name

    # not found, find the closest one
    def color_distance(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> int:
        return sum((a - b) ** 2 for a, b in zip(c1, c2, strict=True))

    closest_name = ""
    closest_distance = float("inf")
    for name, value in ALL_COLORS.items():
        dist = color_distance(rgb, value)
        if dist < closest_distance:
            closest_distance = dist
            closest_name = name
    return closest_name


_NORMALIZED_COLOR_NAMES: dict[str, str] = {name.lower().replace(" ", "_"): name for name in ALL_COLORS}


def normalize_color_name(name: str) -> str | None:
    if name == "Transparent":
        return name

    name = name.strip().lower().replace(" ", "_")
    return _NORMALIZED_COLOR_NAMES.get(name)


def parse_color_names(names: Sequence[str]) -> Sequence[str]:
    result: list[str] = []
    idx = 0
    while idx < len(names):
        for length in range(2, -1, -1):
            if idx + length >= len(names):
                continue
            name = "_".join(names[idx : idx + length + 1]).lower().strip()
            if (color_name := _NORMALIZED_COLOR_NAMES.get(name)) is not None:
                result.append(color_name)
                idx += length + 1
                break
        else:
            idx += 1
    return result


def parse_rgb_str(s: str) -> tuple[int, int, int] | None:
    if not (s := s.removeprefix("#").lower()) or len(s) != 6:
        return None

    if any(c not in "0123456789abcdef" for c in s):
        return None

    r, g, b = (int(s[i : i + 2], 16) for i in (0, 2, 4))
    return r, g, b
