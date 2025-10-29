import base64
import contextlib
import json
import random
from collections.abc import AsyncGenerator
from enum import Enum
from typing import Any, Self

import anyio

from .assets import assets
from .browser import get_browser
from .config import WplaceCredentials
from .consts import COLORS_ID
from .log import escape_tag, logger
from .schemas import WplaceUserInfo
from .utils import WplacePixelCoords

PAINT_BTN_SELECTOR = ".disable-pinch-zoom > div.absolute .btn.btn-primary.btn-lg"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)


async def fetch_user_info(credentials: WplaceCredentials) -> WplaceUserInfo:
    async with (
        await get_browser(headless=True) as browser,
        await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1920, "height": 1080},
            java_script_enabled=True,
        ) as context,
    ):
        await context.add_init_script(assets.page_init.replace("{{color_id}}", "1"))
        await context.add_cookies(credentials.to_cookies())
        async with await context.new_page() as page:
            resp = await page.goto(
                "https://backend.wplace.live/me",
                wait_until="networkidle",
            )
            if not resp:
                raise RuntimeError("Failed to fetch user info")
            return WplaceUserInfo.model_validate_json(await resp.text())


class ZoomLevel(int, Enum):
    Z_16 = 16.0
    Z_15 = 15.0


_ZOOM_PIXEL_SIZE: dict[ZoomLevel, float] = {
    ZoomLevel.Z_16: 16,
    ZoomLevel.Z_15: 7.65,
}


class WplacePage:
    def __init__(
        self,
        credentials: WplaceCredentials,
        color_name: str,
        coord: WplacePixelCoords,
        zoom: ZoomLevel,
    ) -> None:
        self.credentials = credentials
        self.color_name = color_name
        self.coord = coord
        self.zoom = zoom

    @contextlib.asynccontextmanager
    async def begin(self, script_data: dict[str, Any]) -> AsyncGenerator[Self]:
        scripts = [
            assets.page_init.replace("{{color_id}}", str(COLORS_ID[self.color_name])),
            assets.paint_btn.replace("{{script_data}}", base64.b64encode(json.dumps(script_data).encode()).decode()),
        ]
        async with (
            await get_browser(headless=False) as browser,
            await browser.new_context(viewport={"width": 1280, "height": 720}, java_script_enabled=True) as context,
        ):
            for script in scripts:
                await context.add_init_script(script)
            await context.add_cookies(self.credentials.to_cookies())
            self._btn_id = script_data.get("btn", "paint-button-7685")

            async with await context.new_page() as page:
                url = self.coord.to_share_url(zoom=self.zoom.value)
                await page.goto(url, wait_until="networkidle")

                self.context = context
                self.page = page
                self._current_coord = self.coord.offset(0, 0)

                try:
                    yield self
                finally:
                    del self.context, self.page

    async def find_and_click_paint_btn(self) -> None:
        """Find and click the paint button on the page."""
        if paint_btn := await self.page.query_selector(PAINT_BTN_SELECTOR):
            logger.debug(f"Found paint button: {paint_btn!r}")
            await paint_btn.click()
            logger.info("Clicked paint button")
        else:
            logger.warning("No paint button found on the page")

    async def submit_paint(self) -> None:
        selector = f"#{self._btn_id}"
        btn = await self.page.query_selector(selector)
        if btn is None:
            logger.warning("No submit button found on the page")
            return

        logger.opt(colors=True).debug(f"Found submit button <c>{selector}</>: {escape_tag(repr(btn))}")
        await btn.click()
        logger.info("Clicked submit button")
        while await self.page.query_selector(selector):
            logger.debug("Waiting for submit to complete...")
            await anyio.sleep(1)
        logger.info("Submit completed")

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

    async def _move_by_pixel(self, dx: int, dy: int) -> None:
        """Move the page by pixel offsets."""
        pixel_size = _ZOOM_PIXEL_SIZE[self.zoom]
        x, y = self.current_center_px
        await self.page.mouse.up(button="left")
        await self.page.mouse.move(x, y)
        await self.page.mouse.down(button="left")
        await self.page.mouse.move(
            x - dx * pixel_size,
            y - dy * pixel_size,
            steps=random.randint(7, 15),
        )
        await anyio.sleep(0.175)
        await self.page.mouse.up(button="left")
        self._current_coord = self._current_coord.offset(dx, dy)

    async def move_by_pixel(self, dx: int, dy: int) -> None:
        if dx:
            await self._move_by_pixel(dx, 0)
        if dy:
            await self._move_by_pixel(0, dy)

    async def click_current_pixel(self) -> None:
        """Click the current pixel on the page."""
        await self.page.mouse.up(button="left")
        await self.page.mouse.click(*self.current_center_px, delay=0.05, button="left")
