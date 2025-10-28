# ruff: noqa: N815
import base64
import functools
import math
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel

from .consts import FREE_COLORS, PAID_COLORS
from .utils import WplacePixelCoords, get_flag_emoji


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

    def format_target_droplets(self, target_droplets: int) -> str:
        droplets_needed = target_droplets - self.droplets
        pixels_to_paint = 0
        current_level = int(self.level)
        droplets_gained = 0

        while droplets_gained < droplets_needed:
            pixels_to_next_level = math.ceil(math.pow(current_level * math.pow(30, 0.65), (1 / 0.65))) - (
                self.pixelsPainted + pixels_to_paint
            )

            # 如果仅靠绘制像素就能达到目标
            if droplets_gained + pixels_to_next_level >= droplets_needed:
                pixels_to_paint += droplets_needed - droplets_gained
                break

            # 升级
            pixels_to_paint += pixels_to_next_level
            droplets_gained += pixels_to_next_level + 500  # 绘制像素+升级奖励
            current_level += 1

        # 减去当前已有的像素
        net_pixels_needed = pixels_to_paint - self.charges.count
        total_seconds = max(0, net_pixels_needed) * self.charges.cooldownMs / 1000.0
        eta_time = datetime.now() + timedelta(seconds=total_seconds)

        return f"[目标: 💧{target_droplets}] 还需 {pixels_to_paint} 像素\n预计达成: {eta_time:%Y-%m-%d %H:%M}"

    def format_notification(self, target_droplets: int | None = None) -> str:
        flag = f" {get_flag_emoji(self.equippedFlag)}" if self.equippedFlag else ""
        remaining = timedelta(seconds=max(0, int(self.charges.remaining_secs())))
        recover_time = datetime.now() + remaining
        base_msg = (
            f"{self.name} #{self.id}{flag} 💧{self.droplets}\n"
            f"Lv. {int(self.level)} (升级还需 {self.next_level_pixels()} 像素)\n"
            f"当前像素: {int(self.charges.count)}/{self.charges.max}\n"
            f"恢复耗时: {remaining}\n"
            f"预计回满: {recover_time.replace(microsecond=0).isoformat(' ')}"
        )

        if target_droplets is None or target_droplets <= self.droplets:
            return base_msg
        extra_msg = self.format_target_droplets(target_droplets)
        return f"{base_msg}\n{extra_msg}"

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
