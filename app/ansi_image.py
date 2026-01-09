import shutil
import sys
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from PIL import Image


def draw_ansi(img: Image.Image) -> None:
    (width, height), (cols, rows) = img.size, shutil.get_terminal_size()
    img = img.convert("RGBA").resize(
        (cols, int(height / width * cols * 0.55))
        if width / cols > height / (rows - 1) * 0.55
        else (int(width / height * (rows - 1) / 0.55), rows - 1)
    )
    for y in range(img.height):
        line = ""
        for x in range(img.width):
            r, g, b, a = cast("tuple[int, int, int, int]", img.getpixel((x, y)))
            line += f"\033[38;2;{r};{g};{b}m█\033[0m" if a > 0 else " "
        sys.stdout.write(line + "\n")
    sys.stdout.flush()
