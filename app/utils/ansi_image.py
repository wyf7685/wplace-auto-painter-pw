import shutil
import sys
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from typing import Protocol, TextIO

    from PIL.Image import Image

    type Cols = int
    type Rows = int
    type RGBA = tuple[int, int, int, int]

    class PixelAccess[TPixel](Protocol):
        def __getitem__(self, xy: tuple[int, int]) -> TPixel: ...
        def __setitem__(self, xy: tuple[int, int], color: TPixel) -> None: ...


def draw_ansi(
    img: Image,
    file: TextIO = sys.stdout,
    max_size: tuple[Cols, Rows] | None = None,
) -> None:
    img = img.convert("RGBA")

    width, height = img.size
    if max_size is not None or file.isatty():
        cols, rows = shutil.get_terminal_size() if max_size is None else max_size
        img = img.resize(
            (cols, int(height / width * cols * 0.55))
            if width / cols > height / (rows - 1) * 0.55
            else (int(width / height * (rows - 1) / 0.55), rows - 1)
        )

    data = cast("PixelAccess[RGBA]", img.load())
    for y in range(img.height):
        chars = [
            (f"\033[38;2;{r};{g};{b}m█\033[0m" if a > 0 else " ")
            for r, g, b, a in (data[x, y] for x in range(img.width))
        ]
        file.write("".join(chars) + "\n")
    file.flush()
