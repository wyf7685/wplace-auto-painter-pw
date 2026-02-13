import functools
import json
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal

from bot7685_ext.wplace.consts import COLORS_ID, ColorName
from pydantic import BaseModel, Field, SecretStr

from app.utils import SecretStrEncoder, WplacePixelCoords

if TYPE_CHECKING:
    from PIL import Image
    from playwright._impl._api_structures import SetCookieParam


DATA_DIR = Path.cwd().resolve().joinpath("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR = DATA_DIR / "templates"
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = DATA_DIR / "config.json"
CONFIG_SCHEMA_FILE = DATA_DIR / ".config.schema.json"


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


class TemplateConfig(BaseModel):
    file_id: str = Field(description="Template image file name without extension")
    coords: WplacePixelCoords = Field(description="Top-left pixel coordinates of the template on the canvas")

    @property
    def file(self) -> Path:
        return TEMPLATES_DIR / f"{self.file_id}.png"

    def load_im(self) -> Image.Image:
        from PIL import Image

        return Image.open(self.file)

    def get_coords(self) -> tuple[WplacePixelCoords, WplacePixelCoords]:
        w, h = self.load_im().size
        return self.coords, self.coords.offset(w - 1, h - 1)

    def crop(self, selected: tuple[int, int, int, int]) -> CroppedTemplateConfig:
        return CroppedTemplateConfig(
            file_id=self.file_id,
            coords=self.coords,
            selected=selected,
        )


class CroppedTemplateConfig(TemplateConfig):
    selected: tuple[int, int, int, int]

    def load_im(self) -> Image.Image:
        x, y, w, h = self.selected
        return super().load_im().crop((x, y, x + w, y + h))

    def get_coords(self) -> tuple[WplacePixelCoords, WplacePixelCoords]:
        x, y, w, h = self.selected
        st = self.coords.offset(x, y)
        ed = st.offset(w - 1, h - 1)
        return st, ed

    def crop(self, selected: tuple[int, int, int, int]) -> CroppedTemplateConfig:
        x0, y0, _, _ = self.selected
        x1, y1, w, h = selected
        x, y = x0 + x1, y0 + y1
        return super().crop((x, y, w, h))


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


class Config(BaseModel):
    _cache: ClassVar[Config | None] = None

    users: list[UserConfig] = Field(description="List of user configurations")
    browser: Literal["chromium", "firefox", "webkit", "chrome", "msedge"] = Field(
        description="Playwright browser type to use"
    )
    proxy: str | None = Field(default=None, description="Optional proxy server URL to access wplace")
    log_level: Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="DEBUG", description="Logging level for console"
    )
    check_update: bool = Field(default=True, description="Whether to check for updates")

    @classmethod
    def load(cls) -> Config:
        if cls._cache is None:
            cls._cache = cls.model_validate_json(CONFIG_FILE.read_text("utf-8"), extra="ignore")
        return cls._cache

    def save(self) -> None:
        CONFIG_FILE.write_text(
            json.dumps(
                {"$schema": CONFIG_SCHEMA_FILE.relative_to(CONFIG_FILE.parent).as_posix()}
                | self.model_dump(exclude_defaults=True),
                indent=2,
                ensure_ascii=False,
                cls=SecretStrEncoder,
            ),
            encoding="utf-8",
        )
        Config._cache = self


def export_config_schema() -> None:
    CONFIG_SCHEMA_FILE.write_text(json.dumps(Config.model_json_schema()), encoding="utf-8")
