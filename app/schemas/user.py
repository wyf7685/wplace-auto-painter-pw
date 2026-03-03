import functools
from typing import TYPE_CHECKING, Literal

from bot7685_ext.wplace.consts import COLORS_ID, ColorName
from pydantic import BaseModel, Field, SecretStr

from .template import TemplateConfig

if TYPE_CHECKING:
    from playwright._impl._api_structures import SetCookieParam


def _construct_pw_cookie(name: str, value: str) -> SetCookieParam:
    return {
        "name": name,
        "value": value,
        "domain": ".backend.wplace.live",
        "path": "/",
        "httpOnly": False,
        "secure": True,
        "sameSite": "Lax",
    }


class WplaceCredentials(BaseModel):
    token: SecretStr = Field(description="WPlace cookie 'j' value")
    cf_clearance: SecretStr | None = Field(
        default=None, description="WPlace cookie 'cf_clearance' value, could be null if not needed"
    )

    def to_pw_cookies(self) -> list[SetCookieParam]:
        cookies: list[SetCookieParam] = [_construct_pw_cookie("j", self.token.get_secret_value())]
        if self.cf_clearance:
            cookies.append(_construct_pw_cookie("cf_clearance", self.cf_clearance.get_secret_value()))
        return cookies

    def to_requests_cookies(self) -> dict[str, str]:
        cookies: dict[str, str] = {"j": self.token.get_secret_value()}
        if self.cf_clearance:
            cookies["cf_clearance"] = self.cf_clearance.get_secret_value()
        return cookies


class PurchaseMaxChargeConfig(BaseModel):
    type: Literal["max_charges"]
    target_max: int | None = None
    retain_droplets: int = 0


class PurchaseChargeConfig(BaseModel):
    type: Literal["charges"]
    retain_droplets: int = 0


class UserConfig(BaseModel):
    identifier: str = Field(description="User identifier, for logging purposes")
    credentials: WplaceCredentials = Field(description="Wplace authentication credentials")
    template: TemplateConfig = Field(description="Template configuration")
    preferred_colors: list[ColorName] = Field(
        default_factory=list,
        description="List of preferred color names to use when painting, in order of preference",
    )
    selected_area: tuple[int, int, int, int] | None = Field(
        default=None,
        description="Optional selected area on the template image as (x, y, w, h)",
    )
    auto_purchase: PurchaseMaxChargeConfig | PurchaseChargeConfig | None = Field(
        default=None,
        description="Optional automatic charge purchasing configuration",
    )
    min_paint_charges: int = Field(
        default=30,
        description="Minimum number of charges required to start painting",
    )
    max_paint_charges: int | None = Field(
        default=None,
        description="Maximum number of charges to use for single paint loop, null means no limit",
    )

    @functools.cached_property
    def preferred_colors_rank(self) -> list[int]:
        ranks = [len(COLORS_ID)] * (len(COLORS_ID) + 1)
        for r, name in enumerate[ColorName](self.preferred_colors):
            ranks[COLORS_ID[name]] = r
        return ranks
