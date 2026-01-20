import datetime as dt
import math
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple, Self

if TYPE_CHECKING:
    from collections.abc import Iterable


UTC8 = dt.timezone(dt.timedelta(hours=8))

# 从多点校准中提取的常量参数
SCALE_X = 325949.3234522017
SCALE_Y = -325949.3234522014
OFFSET_X = 1023999.5
OFFSET_Y = 1023999.4999999999

WPLACE_TILE_SIZE = 1000  # 每个 tile 包含 1000x1000 像素


class WplaceAbsCoords(NamedTuple):
    x: int
    y: int

    def offset(self, dx: int, dy: int) -> WplaceAbsCoords:
        return WplaceAbsCoords(self.x + dx, self.y + dy)

    def to_pixel(self) -> WplacePixelCoords:
        tlx, pxx = divmod(self.x, WPLACE_TILE_SIZE)
        tly, pxy = divmod(self.y, WPLACE_TILE_SIZE)
        return WplacePixelCoords(tlx, tly, pxx, pxy)


class LatLon(NamedTuple):
    lat: float
    lon: float

    def to_pixel(self) -> WplacePixelCoords:
        return WplacePixelCoords.from_lat_lon(self.lat, self.lon)


# Blue Marble 格式
# f"Tl X: {self.tlx}, Tl Y: {self.tly}, Px X: {self.pxx}, Px Y: {self.pxy}"
BLUE_MARBLE_COORDS_PATTERN = re.compile(r".*Tl X: (\d+), Tl Y: (\d+), Px X: (\d+), Px Y: (\d+).*")


@dataclass
class WplacePixelCoords:
    # each tile contains 1000x1000 pixels, from 0 to 999
    tlx: int  # tile X
    tly: int  # tile Y
    pxx: int  # pixel X
    pxy: int  # pixel Y

    def human_repr(self) -> str:
        return f"({self.tlx}, {self.tly}) + ({self.pxx}, {self.pxy})"

    def to_abs(self) -> WplaceAbsCoords:
        return WplaceAbsCoords(
            self.tlx * WPLACE_TILE_SIZE + self.pxx,
            self.tly * WPLACE_TILE_SIZE + self.pxy,
        )

    def offset(self, dx: int, dy: int) -> WplacePixelCoords:
        return self.to_abs().offset(dx, dy).to_pixel()

    def to_lat_lon(self) -> LatLon:
        x, y = self.to_abs()

        # 从像素坐标计算墨卡托坐标
        merc_x = (x - OFFSET_X) / SCALE_X
        merc_y = (y - OFFSET_Y) / SCALE_Y

        # 从墨卡托坐标计算经纬度
        lon = math.degrees(merc_x)
        lat = math.degrees(2 * math.atan(math.exp(merc_y)) - math.pi / 2)

        return LatLon(lat, lon)

    def to_share_url(self, zoom: float = 20) -> str:
        lat, lon = self.to_lat_lon()
        return f"https://wplace.live/?lat={lat}&lng={lon}&zoom={zoom}"

    def to_blue_marble_str(self) -> str:
        return f"(Tl X: {self.tlx}, Tl Y: {self.tly}, Px X: {self.pxx}, Px Y: {self.pxy})"

    @classmethod
    def from_lat_lon(cls, lat: float, lon: float) -> WplacePixelCoords:
        # 计算墨卡托坐标
        merc_x = math.radians(lon)
        merc_y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))

        # 计算像素绝对坐标
        abs_x = int(merc_x * SCALE_X + OFFSET_X)
        abs_y = int(merc_y * SCALE_Y + OFFSET_Y)

        return WplaceAbsCoords(abs_x, abs_y).to_pixel()

    @classmethod
    def parse(cls, s: str) -> Self:
        if not (m := BLUE_MARBLE_COORDS_PATTERN.match(s)):
            raise ValueError(f"Invalid coords: {s}")
        return cls(int(m[1]), int(m[2]), int(m[3]), int(m[4]))

    def fix_with(self, other: WplacePixelCoords) -> tuple[WplacePixelCoords, WplacePixelCoords]:
        (x1, y1), (x2, y2) = self.to_abs(), other.to_abs()
        (x1, x2), (y1, y2) = sorted((x1, x2)), sorted((y1, y2))
        return WplaceAbsCoords(x1, y1).to_pixel(), WplaceAbsCoords(x2, y2).to_pixel()

    def all_tile_coords(self, other: WplacePixelCoords) -> Iterable[tuple[int, int]]:
        coord1, coord2 = self.fix_with(other)
        yield from ((x, y) for x in range(coord1.tlx, coord2.tlx + 1) for y in range(coord1.tly, coord2.tly + 1))

    def size_with(self, other: WplacePixelCoords) -> tuple[int, int]:
        coord1, coord2 = self.fix_with(other)
        (x1, y1), (x2, y2) = coord1.to_abs(), coord2.to_abs()
        return x2 - x1 + 1, y2 - y1 + 1

    def tuple(self) -> tuple[int, int, int, int]:
        return self.tlx, self.tly, self.pxx, self.pxy
