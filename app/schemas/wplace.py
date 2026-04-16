import base64
import functools
import math
import re
from datetime import UTC, datetime

from bot7685_ext.wplace.consts import FREE_COLORS, PAID_COLORS
from pydantic import BaseModel, ConfigDict


def alias_generator(name: str) -> str:
    return re.sub(r"_([a-z])", lambda m: m[1].upper(), name)


class Charges(BaseModel):
    model_config = ConfigDict(frozen=True, alias_generator=alias_generator)

    cooldown_ms: int
    count: float
    max: int

    def remaining_secs(self) -> float:
        return (self.max - self.count) * (self.cooldown_ms / 1000.0)


class WplaceUserInfo(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore", alias_generator=alias_generator)

    charges: Charges
    droplets: int
    extra_colors_bitmap: int
    flags_bitmap: str
    id: int
    level: float
    name: str
    pixels_painted: int
    timeout_until: datetime  # in UTC

    def next_level_pixels(self) -> int:
        return math.ceil(math.pow(math.floor(self.level) * math.pow(30, 0.65), (1 / 0.65)) - self.pixels_painted)

    @functools.cached_property
    def own_flags(self) -> frozenset[int]:
        b = base64.b64decode(self.flags_bitmap.encode("ascii"))
        return frozenset(i for i in range(len(b) * 8) if b[-(i // 8) - 1] & (1 << (i % 8)))

    @functools.cached_property
    def own_colors(self) -> frozenset[str]:
        bitmap = self.extra_colors_bitmap
        paid = {color for idx, color in enumerate(PAID_COLORS) if bitmap & (1 << idx)}
        return frozenset({"Transparent"} | set(FREE_COLORS) | paid)

    @functools.cached_property
    def is_timed_out(self) -> bool:
        return self.timeout_until > datetime.now(UTC)
