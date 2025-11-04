import contextlib
import random
from collections.abc import AsyncGenerator
from enum import Enum
from typing import Any, Self

import anyio
from bot7685_ext.wplace.consts import COLORS_NAME

from .assets import assets
from .browser import get_browser
from .config import WplaceCredentials
from .exception import FetchFailed, ShoudQuit
from .log import logger
from .schemas import WplaceUserInfo
from .utils import WplacePixelCoords

PAINT_BTN_SELECTOR = ".disable-pinch-zoom > div.absolute .btn.btn-primary.btn-lg"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)


async def fetch_user_info(credentials: WplaceCredentials) -> WplaceUserInfo:
    async with (
        get_browser(headless=True) as browser,
        await browser.new_context(
            user_agent=USER_AGENT,
            viewport={"width": 1920, "height": 1080},
            java_script_enabled=True,
        ) as context,
    ):
        await context.add_init_script(assets.page_init())
        await context.add_cookies(credentials.to_pw_cookies())
        async with await context.new_page() as page:
            resp = await page.goto("https://backend.wplace.live/me", wait_until="networkidle")
            if not resp:
                raise FetchFailed("Failed to fetch user info")
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
        coord: WplacePixelCoords,
        zoom: ZoomLevel = ZoomLevel.Z_15,
    ) -> None:
        self.credentials = credentials
        self.coord = coord
        self.zoom = zoom

    @contextlib.asynccontextmanager
    async def begin(self, script_data: dict[str, Any], resolved_pixel_map: tuple[str, str]) -> AsyncGenerator[Self]:
        self._btn_id = f"fill-btn-{random.randint(1000, 9999)}"
        async with (
            get_browser(headless=False) as browser,
            await browser.new_context(viewport={"width": 1280, "height": 720}, java_script_enabled=True) as context,
        ):
            await context.add_init_script(assets.page_init())
            await context.add_init_script(assets.paint_map(script_data | {"btn": self._btn_id}))
            await context.add_cookies(self.credentials.to_pw_cookies())
            await context.route(
                resolved_pixel_map[0],
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/javascript",
                    body=resolved_pixel_map[1],
                ),
            )

            async with await context.new_page() as page:
                url = self.coord.to_share_url(zoom=self.zoom.value)
                await page.goto(url, wait_until="domcontentloaded")

                try:
                    await page.wait_for_selector(PAINT_BTN_SELECTOR, timeout=10000, state="visible")
                except Exception as e:
                    raise ShoudQuit("Required buttons not found on the page, is the injected script broken?") from e

                self.context = context
                self.page = page
                self._current_coord = self.coord.offset(0, 0)

                try:
                    yield self
                finally:
                    del self.context, self.page

    async def submit_paint(self) -> None:
        selector = f"#{self._btn_id}"
        btn = await self.page.query_selector(selector)
        if btn is None:
            raise ShoudQuit("Fill button not found, is the injected script broken?")

        await btn.click()
        logger.debug("Clicked fill button")
        with anyio.fail_after(30):
            while await self.page.query_selector(selector):
                logger.debug("Waiting for fill to complete...")
                await anyio.sleep(1)

        btn = await self.page.query_selector(PAINT_BTN_SELECTOR)
        if btn is None:
            raise ShoudQuit("Paint button not found after filling, is the injected script broken?")

        await btn.click()
        logger.info("Clicked submit button")
        with anyio.fail_after(30):
            while (btn := await self.page.query_selector(PAINT_BTN_SELECTOR)) and await btn.get_attribute("disabled"):
                logger.debug("Waiting for submit to complete...")
                await anyio.sleep(1)
        logger.success("Submit completed")

    async def find_and_close_modal(self) -> None:
        if modal := await self.page.query_selector(".modal[open]"):
            logger.info(f"Found modal dialog: {modal!r}")
            for el in await modal.query_selector_all("button.btn"):
                if await el.text_content() == "Close":
                    await el.click()
                    logger.success("Closed modal dialog")
                    return
            logger.info("No Close button found in modal dialog")

    @contextlib.asynccontextmanager
    async def open_paint_panel(self) -> AsyncGenerator[None]:
        await self.find_and_close_modal()
        paint_btn = await self.page.query_selector(PAINT_BTN_SELECTOR)
        if paint_btn is None:
            raise ShoudQuit("No paint button found on the page")

        logger.debug(f"Found paint button: {paint_btn!r}")
        await paint_btn.click()
        logger.debug("Clicked paint button")

        yield

        btns = await self.page.query_selector_all(".w-full .items-center > .btn.btn-circle.btn-sm")
        if not btns:
            logger.warning("No close button found on the paint panel. Maybe it's already closed?")
            return
        close_btn = btns[-1]
        logger.debug(f"Found close button: {close_btn!r}")
        await close_btn.click()
        logger.debug("Closed paint panel")

    @contextlib.asynccontextmanager
    async def open_store_panel(self) -> AsyncGenerator[None]:
        store_btn = await self.page.query_selector('.btn[title="Store"]')
        if store_btn is None:
            raise ShoudQuit("Store button not found on the page")

        logger.debug(f"Found store button: {store_btn!r}")
        await store_btn.click()
        logger.debug("Opened store panel")

        yield

        close_btn = await self.page.query_selector(".modal[open] .btn.btn-sm.btn-circle.btn-ghost")
        if close_btn is None:
            logger.warning("No close button found on the store panel")
            return
        logger.debug(f"Found close button: {close_btn!r}")
        await close_btn.click()
        logger.debug("Closed store panel")

    async def select_color(self, color_id: int) -> None:
        color_btn = await self.page.query_selector(f"#color-{color_id}")
        if color_btn is None:
            raise ShoudQuit(f"Color button with ID {color_id} not found on the page")

        logger.debug(f"Found color button: {color_btn!r}")
        await color_btn.click()
        logger.opt(colors=True).info(f"Selected color <g>{COLORS_NAME[color_id]}</>(id=<c>{color_id}</>)")

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
        await anyio.sleep(random.uniform(0.1, 0.3))
        await self.page.mouse.up(button="left")
        self._current_coord = self._current_coord.offset(dx, dy)

    async def move_by_pixel(self, dx: int, dy: int) -> None:
        step_size = 30
        while dx:
            step = max(-step_size, min(step_size, dx))
            await self._move_by_pixel(step, 0)
            dx -= step

        while dy:
            step = max(-step_size, min(step_size, dy))
            await self._move_by_pixel(0, step)
            dy -= step

    async def click_current_pixel(self) -> None:
        """Click the current pixel on the page."""
        await self.page.mouse.up(button="left")
        await self.page.mouse.click(*self.current_center_px, delay=0.05, button="left")
