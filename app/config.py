from pathlib import Path
from typing import ClassVar

from PIL import Image
from playwright._impl._api_structures import SetCookieParam
from pydantic import BaseModel

from .utils import WplacePixelCoords

DATA_DIR = Path("data")
CONFIG_FILE = DATA_DIR.joinpath("config.json")
TEMPLATE_FILE = DATA_DIR.joinpath("template.png")


def _construct_pw_cookie(name: str, value: str) -> SetCookieParam:
    return {
        "name": name,
        "value": value,
        "domain": "backend.wplace.live",
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
    file: ClassVar[Path] = TEMPLATE_FILE
    coords: WplacePixelCoords

    def load(self) -> tuple[Image.Image, tuple[WplacePixelCoords, WplacePixelCoords]]:
        im = Image.open(self.file)
        w, h = im.size
        return im, (self.coords, self.coords.offset(w - 1, h - 1))


class Config(BaseModel):
    template: TemplateConfig
    credentials: WplaceCredentials
    proxy: str | None = None


config = Config.model_validate_json(CONFIG_FILE.read_text("utf-8"))
