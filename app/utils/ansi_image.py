import shutil
from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol, cast

if TYPE_CHECKING:
    from PIL.Image import Image

type Cols = int
type Rows = int
type RGBA = tuple[int, int, int, int]


class PixelAccess[TPixel](Protocol):
    def __getitem__(self, xy: tuple[int, int]) -> TPixel: ...
    def __setitem__(self, xy: tuple[int, int], color: TPixel) -> None: ...


def draw_ansi(
    img: Image,
    write_line: Callable[[str], object],
    max_size: tuple[Cols, Rows] | None = None,
    prefix_length: int = 0,
) -> None:
    img = img.convert("RGBA")

    width, height = img.size
    cols, rows = shutil.get_terminal_size() if max_size is None else max_size
    cols = max(1, cols - prefix_length)
    img = img.resize(
        (cols, int(height / width * cols * 0.55))
        if width / cols > height / (rows - 1) * 0.55
        else (int(width / height * (rows - 1) / 0.55), rows - 1)
    )

    data = cast("PixelAccess[RGBA]", img.load())
    for y in range(img.height):
        chars = [
            (f"<fg #{r:02x}{g:02x}{b:02x}>█</>" if a > 0 else " ")
            for r, g, b, a in (data[x, y] for x in range(img.width))
        ]
        write_line("".join(chars))
