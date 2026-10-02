from typing import TYPE_CHECKING

from .common import switch_color, take_short_break

if TYPE_CHECKING:
    from app.utils.func import LoggerWrapper
    from app.wplace.page import WplacePage
    from app.wplace.page.panel import PaintPanel

    from .common import Pixel


async def paint_pixels(pixels: list[Pixel], page: WplacePage, paint: PaintPanel, log: LoggerWrapper) -> None:
    previous = pixels[0]
    for current in pixels:
        await switch_color(paint, previous.color, current.color, log)
        await page.move_by_pixel(current.x - previous.x, current.y - previous.y)
        await page.click_current_pixel()
        previous = current
        await take_short_break(log)
