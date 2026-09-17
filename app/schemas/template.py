from pathlib import Path

from bot7685_ext.wplace import template_dimensions
from pydantic import BaseModel, Field, field_validator

from app.const import TEMPLATES_DIR

from .coords import WplacePixelCoords


class TemplateConfig(BaseModel):
    file_id: str = Field(description="Template image file name without extension")
    coords: WplacePixelCoords = Field(description="Top-left pixel coordinates of the template on the canvas")

    @field_validator("file_id")
    @classmethod
    def validate_file_id(cls, value: str) -> str:
        file_id = value.strip()
        if not file_id:
            raise ValueError("template.file_id cannot be empty")
        return file_id

    @property
    def file(self) -> Path:
        return TEMPLATES_DIR / f"{self.file_id}.png"

    def read_bytes(self) -> bytes:
        return self.file.read_bytes()

    @property
    def crop_area(self) -> tuple[int, int, int, int] | None:
        return None

    def get_coords(self) -> tuple[WplacePixelCoords, WplacePixelCoords]:
        w, h = template_dimensions(self.read_bytes())
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

    @property
    def crop_area(self) -> tuple[int, int, int, int]:
        return self.selected

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
