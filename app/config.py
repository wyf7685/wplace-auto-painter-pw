import json
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal, Self

from bot7685_ext.wplace.consts import ColorName
from pydantic import BaseModel, Field

from .utils import WplacePixelCoords

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
    token: str = Field(description="Playwright cookie 'j' value")
    cf_clearance: str | None = Field(
        default=None, description="Playwright cookie 'cf_clearance' value, could be null if not needed"
    )

    def to_cookies(self) -> list[SetCookieParam]:
        cookies: list[SetCookieParam] = [_construct_pw_cookie("j", self.token)]
        if self.cf_clearance:
            cookies.append(_construct_pw_cookie("cf_clearance", self.cf_clearance))
        return cookies


class TemplateConfig(BaseModel):
    file_id: str = Field(description="Template image file name without extension")
    coords: WplacePixelCoords = Field(description="Top-left pixel coordinates of the template on the canvas")

    @property
    def file(self) -> Path:
        return TEMPLATES_DIR / f"{self.file_id}.png"

    def load(self) -> tuple[Image.Image, tuple[WplacePixelCoords, WplacePixelCoords]]:
        from PIL import Image

        im = Image.open(self.file)
        w, h = im.size
        return im, (self.coords, self.coords.offset(w - 1, h - 1))


class UserConfig(BaseModel):
    identifier: str = Field(description="User identifier, for logging purposes")
    credentials: WplaceCredentials = Field(description="Wplace authentication credentials")
    template: TemplateConfig = Field(description="Template configuration")
    preferred_colors: list[ColorName] = Field(
        default_factory=list,
        description="List of preferred color names to use when painting, in order of preference",
    )


class Config(BaseModel):
    _cache: ClassVar[Self | None] = None

    users: list[UserConfig] = Field(description="List of user configurations")
    browser: Literal["chromium", "firefox", "webkit", "chrome", "msedge"] = Field(
        description="Playwright browser type to use"
    )

    @classmethod
    def load(cls) -> Self:
        if cls._cache is None:
            cls._cache = cls.model_validate_json(CONFIG_FILE.read_text("utf-8"))
        return cls._cache


def export_config_schema() -> None:
    CONFIG_SCHEMA_FILE.write_text(
        json.dumps(Config.model_json_schema(), indent=2),
        encoding="utf-8",
    )
