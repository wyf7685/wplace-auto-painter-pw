from pathlib import Path

import anyio
import pytest
from bot7685_ext.wplace import compose_tiles
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage

import app.schemas.template as template_module
import app.wplace.template as diff_module
from app.schemas import TemplateConfig, WplacePixelCoords


@pytest.fixture
def template_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setattr(template_module, "TEMPLATES_DIR", tmp_path)
    return tmp_path


def _write_template(directory: Path, width: int, height: int) -> TemplateConfig:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(Qt.GlobalColor.transparent)
    image.setPixelColor(width - 1, height - 1, QColor(Qt.GlobalColor.white))
    assert image.save(str(directory / "fixture.png"))
    return TemplateConfig(
        file_id="fixture",
        coords=WplacePixelCoords(tlx=1718, tly=854, pxx=998, pxy=999),
    )


@pytest.mark.parametrize(
    ("selected", "expected"),
    [
        ((1, 2, 3, 2), (1, 2, 3, 2)),
        ((6, 2, 7, 2), (6, 2, 2, 2)),
        ((1, 4, 2, 7), (1, 4, 2, 2)),
        ((7, 5, 9, 9), (7, 5, 1, 1)),
    ],
)
def test_selected_area_intersects_template_bounds(
    template_dir: Path,
    selected: tuple[int, int, int, int],
    expected: tuple[int, int, int, int],
) -> None:
    template = _write_template(template_dir, 8, 6)
    cropped = template.crop(selected)

    assert cropped.crop_area == expected
    start, end = cropped.get_coords()
    x, y, width, height = expected
    assert start.to_abs() == (1_718_998 + x, 854_999 + y)
    assert end.to_abs() == (1_718_998 + x + width - 1, 854_999 + y + height - 1)


@pytest.mark.parametrize("selected", [(8, 0, 1, 1), (0, 6, 1, 1), (20, 20, 3, 4)])
def test_selected_area_rejects_empty_intersection(
    template_dir: Path,
    selected: tuple[int, int, int, int],
) -> None:
    template = _write_template(template_dir, 8, 6)

    with pytest.raises(ValueError, match="does not overlap"):
        template.crop(selected)


async def _blank_preview(coord1: WplacePixelCoords, coord2: WplacePixelCoords) -> bytes:
    return await compose_tiles([], coord1.as_tuple(), coord2.as_tuple())


def test_oversized_selected_area_diff_uses_template_extent(
    template_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = _write_template(template_dir, 708, 700)
    template.coords = WplacePixelCoords(tlx=1718, tly=854, pxx=944, pxy=175)
    cropped = template.crop((0, 0, 1472, 2300))
    monkeypatch.setattr(diff_module, "download_preview", _blank_preview)

    async def calculate() -> None:
        entries = await diff_module.calc_template_diff(cropped, include_pixels=True)
        assert [(entry.name, entry.count, entry.total, entry.pixels) for entry in entries] == [
            ("White", 1, 1, [(707, 699)])
        ]

    anyio.run(calculate)
    assert cropped.get_coords() == (
        WplacePixelCoords(tlx=1718, tly=854, pxx=944, pxy=175),
        WplacePixelCoords(tlx=1719, tly=854, pxx=651, pxy=874),
    )


def test_clipped_selected_area_diff_keeps_crop_relative_pixels(
    template_dir: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    template = _write_template(template_dir, 8, 6)
    cropped = template.crop((6, 4, 20, 20))
    monkeypatch.setattr(diff_module, "download_preview", _blank_preview)

    async def calculate() -> None:
        entries = await diff_module.calc_template_diff(cropped, include_pixels=True)
        assert [(entry.name, entry.count, entry.total, entry.pixels) for entry in entries] == [
            ("White", 1, 1, [(1, 1)])
        ]

    anyio.run(calculate)
    assert cropped.get_coords()[0].offset(1, 1) == WplacePixelCoords(tlx=1719, tly=855, pxx=5, pxy=4)
