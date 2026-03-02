# ruff: noqa: N815
import base64
import functools
import math
from datetime import datetime
from typing import Any

from bot7685_ext.wplace.consts import FREE_COLORS, PAID_COLORS
from pydantic import BaseModel

from app.utils import WplacePixelCoords


class Charges(BaseModel):
    cooldownMs: int
    count: float
    max: int

    def remaining_secs(self) -> float:
        return (self.max - self.count) * (self.cooldownMs / 1000.0)


class FavoriteLocation(BaseModel):
    id: int
    name: str = ""
    latitude: float
    longitude: float

    def as_coords(self) -> WplacePixelCoords:
        return WplacePixelCoords.from_lat_lon(self.latitude, self.longitude)


class Badge(BaseModel):
    id: int
    imageUrl: str
    name: str
    rarity: str


class WplaceUserInfo(BaseModel):
    allianceId: int | None = None
    allianceRole: str | None = None
    charges: Charges
    country: str
    discord: str = ""
    discordId: str = ""
    droplets: int
    equippedBadges: list[Badge | None]  # len() == 3, None when not equipped
    equippedFlag: int = 0  # 0 when not equipped
    equippedFrameId: int = 0  # 0 when not equipped
    equippedFrameUrl: str = ""  # "" when not equipped
    equippedNameCosmetic: dict[str, Any]
    experiments: dict[str, Any]
    extraColorsBitmap: int
    favoriteLocations: list[FavoriteLocation]
    flagsBitmap: str
    id: int
    isCustomer: bool
    level: float
    maxFavoriteLocations: int
    name: str
    needsPhoneVerification: bool
    picture: str
    pixelsPainted: int
    role: str  # maybe enum?
    showLastPixel: bool
    timeoutUntil: datetime

    def next_level_pixels(self) -> int:
        return math.ceil(math.pow(math.floor(self.level) * math.pow(30, 0.65), (1 / 0.65)) - self.pixelsPainted)

    @functools.cached_property
    def own_flags(self) -> frozenset[int]:
        b = base64.b64decode(self.flagsBitmap.encode("ascii"))
        return frozenset(i for i in range(len(b) * 8) if b[-(i // 8) - 1] & (1 << (i % 8)))

    @functools.cached_property
    def own_colors(self) -> frozenset[str]:
        bitmap = self.extraColorsBitmap
        paid = {color for idx, color in enumerate(PAID_COLORS) if bitmap & (1 << idx)}
        return frozenset({"Transparent"} | set(FREE_COLORS) | paid)
