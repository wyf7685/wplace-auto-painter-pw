import re
from pathlib import Path
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field, field_validator

from app.const import TEMPLATES_DIR

from .coords import WplacePixelCoords

if TYPE_CHECKING:
    from PIL import Image


class TemplateConfig(BaseModel):
    file_id: str = Field(description="Template image file name without extension")
    coords: WplacePixelCoords = Field(description="Top-left pixel coordinates of the template on the canvas")

    @field_validator("file_id")
    @classmethod
    def validate_file_id(cls, value: str) -> str:
        file_id = value.strip()
        if not file_id:
            raise ValueError("template.file_id cannot be empty")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", file_id):
            raise ValueError("template.file_id must match [A-Za-z0-9_-]+")
        return file_id

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

    @field_validator("selected")
    @classmethod
    def validate_selected(cls, value: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        x, y, w, h = value
        if x < 0 or y < 0:
            raise ValueError("selected_area x/y must be >= 0")
        if w <= 0 or h <= 0:
            raise ValueError("selected_area width/height must be > 0")
        return value

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
