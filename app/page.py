import abc
import contextlib
import json
import random
from collections.abc import AsyncGenerator
from enum import Enum
from typing import TYPE_CHECKING, Any, Self, override

import anyio
from bot7685_ext.wplace.consts import COLORS_NAME
from pydantic import SecretStr

from app.assets import assets
from app.browser import get_browser
from app.config import Config, WplaceCredentials
from app.exception import FetchFailed, ShoudQuit
from app.highlight import Highlight
from app.log import escape_tag, logger
from app.schemas import WplaceUserInfo
from app.utils import WplacePixelCoords

if TYPE_CHECKING:
    from playwright.async_api import BrowserContext, Page


PAINT_BTN_SELECTOR = ".disable-pinch-zoom > div.absolute .btn.btn-primary.btn-lg"
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/138.0.0.0 Safari/537.36"
)


@contextlib.asynccontextmanager
async def _headless_context(credentials: WplaceCredentials) -> AsyncGenerator[BrowserContext]:
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
        yield context


async def fetch_user_info(credentials: WplaceCredentials) -> WplaceUserInfo:
    async with _headless_context(credentials) as context, await context.new_page() as page:
        resp = await page.goto("https://backend.wplace.live/me", wait_until="networkidle")
        if not resp:
            raise FetchFailed("Failed to fetch user info")
        text = await resp.text()
        cookies = await context.cookies()

        update = False
        for ck in cookies:
            if ck.get("domain") != ".backend.wplace.live":
                continue
            ck_name = ck.get("name")
            ck_value = ck.get("value", "")
            if ck_name == "cf_clearance":
                update = update or (
                    ck_value != credentials.cf_clearance.get_secret_value()
                    if credentials.cf_clearance is not None
                    else True
                )
                credentials.cf_clearance = SecretStr(ck_value)
            elif ck_name == "j":
                update = update or ck_value != credentials.token.get_secret_value()
                credentials.token = SecretStr(ck_value)
        if update:
            logger.info("Updated credentials from fetched cookies")
            Config.load().save()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        logger.opt(colors=True).warning(f"Failed to decode user info JSON: {Highlight.apply(text)}")
        raise FetchFailed("Failed to decode user info") from e

    try:
        return WplaceUserInfo.model_validate(data)
    except ValueError as e:
        logger.opt(colors=True).warning(f"Failed to parse user info: {Highlight.apply(data)}")
        raise FetchFailed("Failed to parse user info") from e


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
    async def begin(self, script_data: dict[str, Any]) -> AsyncGenerator[Self]:
        async with (
            get_browser(headless=False) as browser,
            await browser.new_context(viewport={"width": 1280, "height": 720}, java_script_enabled=True) as context,
        ):
            await context.add_init_script(assets.page_init())
            await context.add_init_script(assets.paint_btn(script_data))
            await context.add_cookies(self.credentials.to_pw_cookies())
            self._btn_id = script_data.get("btn", "paint-button-7685")

            async with await context.new_page() as page:
                url = self.coord.to_share_url(zoom=self.zoom.value)
                await page.goto(url, wait_until="domcontentloaded")

                try:
                    await page.wait_for_selector(PAINT_BTN_SELECTOR, timeout=10000, state="visible")
                    await page.wait_for_selector(f"#{self._btn_id}", timeout=5000, state="attached")
                except Exception as e:
                    raise ShoudQuit("Required buttons not found on the page, is the injected script broken?") from e

                self.context = context
                self.page = page
                self._current_coord = self.coord.offset(0, 0)

                try:
                    yield self
                finally:
                    del self.context, self.page

    async def find_and_close_modal(self) -> None:
        if modal := await self.page.query_selector(".modal[open]"):
            logger.info(f"Found modal dialog: {modal!r}")
            for el in await modal.query_selector_all("button.btn"):
                if await el.text_content() == "Close":
                    await el.click()
                    logger.info("Closed modal dialog")
                    return
            logger.info("No Close button found in modal dialog")

    @contextlib.asynccontextmanager
    async def open_paint_panel(self) -> AsyncGenerator[PaintPanel]:
        await self.find_and_close_modal()
        async with PaintPanel(self.page, self._btn_id) as panel:
            yield panel

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


class BasePanel(abc.ABC):
    def __init__(self, page: Page) -> None:
        self.page = page

    async def __aenter__(self) -> Self:
        await self.open()
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self.close()

    @abc.abstractmethod
    async def open(self) -> None: ...
    @abc.abstractmethod
    async def close(self) -> None: ...


class PaintPanel(BasePanel):
    @override
    def __init__(self, page: Page, btn_id: str) -> None:
        super().__init__(page)
        self._btn_id = btn_id

    @override
    async def open(self) -> None:
        paint_btn = await self.page.query_selector(PAINT_BTN_SELECTOR)
        if paint_btn is None:
            raise ShoudQuit("No paint button found on the page")

        logger.debug(f"Found paint button: {paint_btn!r}")
        await paint_btn.click()
        logger.info("Clicked paint button")

    @override
    async def close(self) -> None:
        btns = await self.page.query_selector_all(".w-full .items-center > .btn.btn-circle.btn-sm")
        if not btns:
            logger.warning("No close button found on the paint panel")
            return
        close_btn = btns[-1]
        logger.debug(f"Found close button: {close_btn!r}")
        await close_btn.click()
        logger.info("Closed paint panel")

    async def select_color(self, color_id: int) -> None:
        color_btn = await self.page.wait_for_selector(f"#color-{color_id}", timeout=5000, state="visible")
        if color_btn is None:
            raise ShoudQuit(f"Color button with ID {color_id} not found on the page")

        logger.debug(f"Found color button: {color_btn!r}")
        await color_btn.click()
        logger.opt(colors=True).info(f"Selected color <g>{COLORS_NAME[color_id]}</>(id=<c>{color_id}</>)")

    async def submit(self) -> None:
        selector = f"#{self._btn_id}"
        btn = await self.page.query_selector(selector)
        if btn is None:
            raise ShoudQuit("Submit button not found, is the injected script broken?")

        logger.opt(colors=True).debug(f"Found submit button <c>{selector}</>: {escape_tag(repr(btn))}")
        await btn.click()
        logger.info("Clicked submit button")
        with anyio.fail_after(30):
            while await self.page.query_selector(selector):
                logger.debug("Waiting for submit to complete...")
                await anyio.sleep(1)
        logger.info("Submit completed")
