# ruff: noqa: N815
import base64
import functools
import math
from datetime import datetime
from enum import Enum
from typing import Any, Literal

from bot7685_ext.wplace.consts import FREE_COLORS, PAID_COLORS
from pydantic import BaseModel

from .utils import WplacePixelCoords


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

    @property
    def coords(self) -> WplacePixelCoords:
        return WplacePixelCoords.from_lat_lon(self.latitude, self.longitude)


class WplaceUserInfo(BaseModel):
    allianceId: int | None = None
    allianceRole: str | None = None
    banned: bool
    charges: Charges
    country: str
    discord: str | None = None
    droplets: int
    equippedFlag: int  # 0 when not equipped
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


class PixelPaintedBy(BaseModel):
    id: int
    name: str
    allianceId: int
    allianceName: str
    equippedFlag: int
    discord: str | None = None


class PixelRegion(BaseModel):
    id: int
    cityId: int
    name: str
    number: int
    countryId: int


class PixelInfo(BaseModel):
    paintedBy: PixelPaintedBy
    region: PixelRegion


class RankUser(BaseModel):
    id: int
    name: str
    allianceId: int
    allianceName: str
    pixelsPainted: int
    equippedFlag: int
    picture: str | None = None


type RankType = Literal["today", "week", "month", "all-time"]


class PurchaseItem(int, Enum):
    MAX_CHARGE_5 = 70
    CHARGE_30 = 80

    @property
    def price(self) -> int:
        return PURCHASE_ITEM_PRICES[self]

    @property
    def item_name(self) -> str:
        return PURCHASE_ITEM_NAMES[self]


PURCHASE_ITEM_PRICES: dict[PurchaseItem, int] = {
    PurchaseItem.MAX_CHARGE_5: 500,
    PurchaseItem.CHARGE_30: 500,
}
PURCHASE_ITEM_NAMES: dict[PurchaseItem, str] = {
    PurchaseItem.MAX_CHARGE_5: "像素上限 x5",
    PurchaseItem.CHARGE_30: "像素余额 x30",
}
