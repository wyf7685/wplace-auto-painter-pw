from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Literal, Self

from pydantic import BaseModel

from .utils import WplacePixelCoords

if TYPE_CHECKING:
    from PIL import Image
    from playwright._impl._api_structures import SetCookieParam


DATA_DIR = Path.cwd().resolve().joinpath("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR = DATA_DIR / "templates"
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = DATA_DIR / "config.json"


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
    token: str
    cf_clearance: str | None = None

    def to_cookies(self) -> list[SetCookieParam]:
        cookies: list[SetCookieParam] = [_construct_pw_cookie("j", self.token)]
        if self.cf_clearance:
            cookies.append(_construct_pw_cookie("cf_clearance", self.cf_clearance))
        return cookies


class TemplateConfig(BaseModel):
    file_id: str
    coords: WplacePixelCoords

    @property
    def file(self) -> Path:
        return TEMPLATES_DIR / f"{self.file_id}.png"

    def load(self) -> tuple[Image.Image, tuple[WplacePixelCoords, WplacePixelCoords]]:
        from PIL import Image

        im = Image.open(self.file)
        w, h = im.size
        return im, (self.coords, self.coords.offset(w - 1, h - 1))


class UserConfig(BaseModel):
    identifier: str
    credentials: WplaceCredentials
    template: TemplateConfig


class Config(BaseModel):
    _cache: ClassVar[Self | None] = None

    users: list[UserConfig]
    browser: Literal["chromium", "firefox", "webkit", "chrome", "msedge"]
    proxy: str | None = None

    @classmethod
    def load(cls) -> Self:
        if cls._cache is None:
            cls._cache = cls.model_validate_json(CONFIG_FILE.read_text("utf-8"))
        return cls._cache
