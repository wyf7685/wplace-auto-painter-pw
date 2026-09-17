import shutil
from collections.abc import Callable

from bot7685_ext.wplace import template_dimensions, template_thumbnail_rgba

type Cols = int
type Rows = int


async def draw_ansi(
    image_bytes: bytes,
    write_line: Callable[[str], object],
    max_size: tuple[Cols, Rows] | None = None,
    prefix_length: int = 0,
    *,
    template_crop: tuple[int, int, int, int] | None = None,
) -> None:
    width, height = template_crop[2:] if template_crop is not None else template_dimensions(image_bytes)

    cols, rows = shutil.get_terminal_size() if max_size is None else max_size
    cols = max(1, cols - prefix_length)
    rows = max(2, rows)
    target_size = (
        (cols, max(1, int(height / width * cols * 0.55)))
        if width / cols > height / (rows - 1) * 0.55
        else (max(1, int(width / height * (rows - 1) / 0.55)), rows - 1)
    )
    pixels = await template_thumbnail_rgba(image_bytes, target_size, template_crop=template_crop)

    width, height = target_size
    for y in range(height):
        row_start = y * width * 4
        chars: list[str] = []
        for x in range(width):
            offset = row_start + x * 4
            r, g, b, a = pixels[offset], pixels[offset + 1], pixels[offset + 2], pixels[offset + 3]
            chars.append(f"<fg #{r:02x}{g:02x}{b:02x}>█</>" if a > 0 else " ")
        write_line("".join(chars))
