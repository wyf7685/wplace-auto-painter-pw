import pytest

from app.schemas import WplacePixelCoords


@pytest.mark.parametrize(
    "raw",
    [
        "123, 456, 789, 12",
        "(Tl X: 123, Tl Y: 456, Px X: 789, Px Y: 12)",
        "template tlx=123 / tly=456; pixel=(789, 12)",
    ],
)
def test_parse_accepts_gui_coordinate_formats(raw: str) -> None:
    assert WplacePixelCoords.parse(raw) == WplacePixelCoords(tlx=123, tly=456, pxx=789, pxy=12)


def test_parse_accepts_coordinate_boundaries() -> None:
    assert WplacePixelCoords.parse("2047, 2047, 999, 0") == WplacePixelCoords(
        tlx=2047,
        tly=2047,
        pxx=999,
        pxy=0,
    )


@pytest.mark.parametrize("raw", ["123, 456, 789", "123, 456, 789, 12, 34"])
def test_parse_requires_exactly_four_numbers(raw: str) -> None:
    with pytest.raises(ValueError, match="Invalid coords"):
        WplacePixelCoords.parse(raw)


@pytest.mark.parametrize(
    "raw",
    [
        "2048, 2047, 999, 0",
        "2047, 2048, 999, 0",
        "2047, 2047, 1000, 0",
        "2047, 2047, 999, 1000",
        "-1, 2047, 999, 0",
        "2047, 2047, -1, 0",
    ],
)
def test_parse_rejects_out_of_range_coordinates(raw: str) -> None:
    with pytest.raises(ValueError, match="Invalid coords"):
        WplacePixelCoords.parse(raw)
