import contextlib
import random
import time
from collections.abc import AsyncGenerator
from enum import Enum
from typing import Self

import anyio
from playwright.async_api import BrowserContext, Page, async_playwright

from app.schemas import FetchMeResponse
from app.utils import WplacePixelCoords

from .config import WplaceCredentials, config
from .log import logger

PW_INIT_SCRIPT = """\
(()=>{
    Object.defineProperty(navigator, 'webdriver', {get: () => undefined})
    localStorage.setItem('view-rules', 'true');
    localStorage.setItem('void-message-2', 'true');
})()
"""


@contextlib.asynccontextmanager
async def open_wplace_url(
    credentials: WplaceCredentials,
    url: str,
) -> AsyncGenerator[tuple[BrowserContext, Page], None]:
    async with (
        async_playwright() as p,
        await p.chromium.launch(headless=False) as browser,
        await browser.new_context() as context,
    ):
        await context.add_init_script(PW_INIT_SCRIPT)
        await context.add_cookies(config.credentials.to_cookies())
        async with await context.new_page() as page:
            await page.goto(url, wait_until="networkidle")
            # await find_and_close_modal(page)
            yield context, page


# async def find_and_close_modal(page: Page):
#     if modal := await page.query_selector(".modal[open]"):
#         logger.info(f"Found modal dialog: {modal!r}")
#         for el in await modal.query_selector_all("button.btn"):
#             if await el.text_content() == "Close":
#                 await el.click()
#                 logger.info("Closed modal dialog")
#                 return
#         logger.info("No Close button found in modal dialog")


PAINT_BTN_SELECTOR = ".disable-pinch-zoom > div.absolute .btn.btn-primary.btn-lg"


class ZoomParams(Enum):
    Z_17_5 = 17.5, 44
    Z_16 = 16., 16
    Z_15 = 15., 8


class WplacePage:
    def __init__(
        self,
        credentials: WplaceCredentials,
        coord: WplacePixelCoords,
        zoom: ZoomParams,
    ) -> None:
        self.credentials = credentials
        self._coord = coord
        self._zoom = zoom

    @contextlib.asynccontextmanager
    async def begin(self) -> AsyncGenerator[Self, None]:
        url = self._coord.to_share_url(zoom=self._zoom.value[0])
        async with open_wplace_url(self.credentials, url) as (self.context, self.page):
            self._current_coord = self._coord.offset(0, 0)
            yield self
        del self.context, self.page

    async def find_and_click_paint_btn(self) -> None:
        """Find and click the paint button on the page."""
        if paint_btn := await self.page.query_selector(PAINT_BTN_SELECTOR):
            logger.info(f"Found paint button: {paint_btn!r}")
            await paint_btn.click()
            logger.info("Clicked paint button")
        else:
            logger.info("No paint button found on the page")

    async def idle_around(self, seconds: float) -> None:
        """Keep the page idle for a while to avoid being detected as a bot.

        Simulates natural user behavior including:
        - Mouse movement
        - Zooming (wheel)
        - Dragging
        """
        start = time.time()
        while time.time() - start < seconds:
            match random.choice(("move", "drag", "zoom")):
                case "move":
                    # Simple mouse movement
                    x = random.randint(100, 800)
                    y = random.randint(100, 600)
                    await self.page.mouse.move(x, y)
                    await self.page.wait_for_timeout(random.randint(200, 500))
                case "zoom":
                    # Simulate zoom by wheel scroll
                    x = random.randint(100, 800)
                    y = random.randint(100, 600)
                    await self.page.mouse.move(x, y)
                    zoom_direction = random.choice([-1, 1])
                    await self.page.mouse.wheel(
                        0, zoom_direction * random.randint(50, 100)
                    )
                    await self.page.wait_for_timeout(random.randint(300, 800))
                case "drag":
                    # Drag interaction
                    start_x = random.randint(100, 600)
                    start_y = random.randint(100, 500)
                    end_x = start_x + random.randint(-100, 100)
                    end_y = start_y + random.randint(-100, 100)

                    await self.page.mouse.move(start_x, start_y)
                    await self.page.mouse.down()
                    await self.page.wait_for_timeout(random.randint(100, 300))

                    # Simulate smooth dragging with intermediate steps
                    steps = random.randint(3, 8)
                    for step in range(steps):
                        progress = (step + 1) / steps
                        current_x = int(start_x + (end_x - start_x) * progress)
                        current_y = int(start_y + (end_y - start_y) * progress)
                        await self.page.mouse.move(current_x, current_y)
                        await self.page.wait_for_timeout(random.randint(30, 100))

                    await self.page.mouse.up()
                    await self.page.wait_for_timeout(random.randint(200, 500))

    @property
    def current_coord(self) -> WplacePixelCoords:
        return self._current_coord

    @property
    def current_page_viewport(self) -> tuple[int, int]:
        viewport = self.page.viewport_size
        if viewport is None:
            raise RuntimeError("Viewport size is not available")
        return viewport["width"], viewport["height"]

    @property
    def current_center_px(self) -> tuple[int, int]:
        w, h = self.current_page_viewport
        return w // 2, h // 2

    async def pixel_move(self, dx: int, dy: int) -> None:
        """Move the page by pixel offsets."""
        pixel_size = self._zoom.value[1]
        x, y = self.current_center_px
        await self.page.mouse.up(button="left")
        await self.page.mouse.move(x, y)
        await self.page.mouse.down(button="left")
        await self.page.mouse.move(
            x - dx * pixel_size,
            y - dy * pixel_size,
            steps=random.randint(7, 15),
        )
        await anyio.sleep(0.1)
        await self.page.mouse.up(button="left")
        self._current_coord = self._current_coord.offset(dx, dy)

    async def click_current_pixel(self) -> None:
        """Click the current pixel on the page."""
        await self.page.mouse.up(button="left")
        await self.page.mouse.click(*self.current_center_px, delay=0.05, button="left")

    async def fetch_user_info(self) -> FetchMeResponse:
        """Fetch the current user info from the backend."""
        async with await self.context.new_page() as api_page:
            resp = await api_page.goto(
                "https://backend.wplace.live/me",
                wait_until="networkidle",
            )
            if not resp:
                raise RuntimeError("Failed to fetch user info")
            return FetchMeResponse.model_validate_json(await resp.text())
