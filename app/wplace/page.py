import abc
import contextlib
import functools
import json
import math
import random
from enum import Enum
from typing import TYPE_CHECKING, Any, Self, override

import anyio
import anyio.to_thread
from bot7685_ext.wplace.consts import COLORS_NAME
from pydantic import SecretStr

from app.browser import get_browser
from app.config import Config
from app.const import APP_NAME, assets
from app.exception import ElementNotFound, FetchFailed
from app.log import escape_tag, logger
from app.schemas import WplaceCredentials, WplacePixelCoords, WplaceUserInfo
from app.utils import Highlight

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

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
        for ck in filter(lambda ck: ck.get("domain") == ".backend.wplace.live", cookies):
            match (ck.get("name"), ck.get("value", "")):
                case ("cf_clearance", ck_val) if (
                    credentials.cf_clearance is None or ck_val != credentials.cf_clearance.get_secret_value()
                ):
                    credentials.cf_clearance = SecretStr(ck_val)
                    update = True
                case ("j", ck_val) if ck_val != credentials.token.get_secret_value():
                    credentials.token = SecretStr(ck_val)
                    update = True
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
    Z_16 = 16
    Z_15 = 15


_ZOOM_PIXEL_SIZE: dict[ZoomLevel, float] = {
    ZoomLevel.Z_16: 16,
    ZoomLevel.Z_15: 7.65,
}


async def notify_open_browser() -> None:
    from app.utils import toast

    logger.debug("Sending notification for opening browser...")
    clicked = await anyio.to_thread.run_sync(
        functools.partial(
            toast.notify_with_button,
            APP_NAME,
            "即将打开浏览器窗口进行绘制操作。",
            button="确认",
        ),
        abandon_on_cancel=True,
    )
    if not clicked:
        logger.info("Toast timed out or dismissed, proceeding to open browser.")


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
        self._pixel_size = _ZOOM_PIXEL_SIZE[zoom]

    @contextlib.asynccontextmanager
    async def open(self, script_data: dict[str, Any]) -> AsyncGenerator[Self]:
        await notify_open_browser()

        async with (
            get_browser(headless=False) as browser,
            await browser.new_context(
                viewport={"width": 1280, "height": 720},
                java_script_enabled=True,
            ) as context,
        ):
            await context.add_init_script(assets.page_init())
            await context.add_init_script(assets.paint_btn(script_data))
            await context.add_cookies(self.credentials.to_pw_cookies())
            self._btn_id = script_data.get("btn", "paint-button-7685")
            logger.opt(colors=True).debug(f"Using paint button ID: <c>{escape_tag(self._btn_id)}</>")

            async with await context.new_page() as page:
                url = self.coord.to_share_url(zoom=self.zoom.value)
                await page.goto(url, wait_until="domcontentloaded")

                try:
                    await page.wait_for_selector(PAINT_BTN_SELECTOR, timeout=10_000, state="visible")
                    await page.wait_for_selector(f"#{self._btn_id}", timeout=10_000, state="attached")
                except _pw_timeout_error() as e:
                    raise ElementNotFound(
                        "Required buttons not found on the page, is the injected script broken?"
                    ) from e

                self.context = context
                self.page = page
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
            logger.warning("No Close button found in modal dialog")

    @contextlib.asynccontextmanager
    async def open_paint_panel(self) -> AsyncGenerator[PaintPanel]:
        await self.find_and_close_modal()
        async with PaintPanel(self.page, self._btn_id) as panel:
            yield panel

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
        if dx == 0 and dy == 0:
            await anyio.sleep(random.uniform(0.01, 0.03))
            return

        center_x, center_y = self.current_center_px
        start_x = center_x + random.uniform(-2.5, 2.5)
        start_y = center_y + random.uniform(-2.5, 2.5)
        target_x = center_x - dx * self._pixel_size
        target_y = center_y - dy * self._pixel_size
        vec_x = target_x - start_x
        vec_y = target_y - start_y
        distance = math.hypot(vec_x, vec_y)

        if distance < 1:
            return

        dir_x = vec_x / distance
        dir_y = vec_y / distance
        normal_x = -dir_y
        normal_y = dir_x

        await self.page.mouse.up(button="left")
        await self.page.mouse.move(start_x, start_y, steps=random.randint(3, 7))
        await anyio.sleep(random.uniform(0.02, 0.08))
        await self.page.mouse.down(button="left")
        await anyio.sleep(random.uniform(0.02, 0.07))

        arc_amplitude = random.uniform(0.6, 2.8)
        if distance > 120:
            arc_amplitude += random.uniform(0.4, 1.6)
        if random.random() < 0.45:
            arc_amplitude *= -1

        steps = max(8, min(40, int(distance / random.uniform(16.0, 24.0))))
        for idx in range(1, steps + 1):
            progress = idx / steps
            # Ease-in/out to avoid perfectly constant velocity.
            eased = 0.5 - 0.5 * math.cos(progress * math.pi)
            curve = math.sin(progress * math.pi) * arc_amplitude
            jitter_scale = 1 - abs(0.5 - progress) * 1.8
            jitter_x = random.uniform(-0.6, 0.6) * max(0.0, jitter_scale)
            jitter_y = random.uniform(-0.6, 0.6) * max(0.0, jitter_scale)

            point_x = start_x + vec_x * eased + normal_x * curve + jitter_x
            point_y = start_y + vec_y * eased + normal_y * curve + jitter_y
            await self.page.mouse.move(point_x, point_y)

            if idx < steps and random.random() < 0.12:
                await anyio.sleep(random.uniform(0.004, 0.018))

        if random.random() < 0.35:
            await self.page.mouse.move(
                target_x + random.uniform(-1.0, 1.0),
                target_y + random.uniform(-1.0, 1.0),
                steps=random.randint(2, 4),
            )
            await anyio.sleep(random.uniform(0.01, 0.04))
            await self.page.mouse.move(target_x, target_y, steps=random.randint(2, 4))

        await anyio.sleep(random.uniform(0.03, 0.11))
        await self.page.mouse.up(button="left")
        await anyio.sleep(random.uniform(0.05, 0.16))

    async def move_by_pixel(self, dx: int, dy: int, max_step: int = 30) -> None:
        if max_step <= 0:
            raise ValueError("max_step must be greater than 0")

        remaining_x, remaining_y = dx, dy
        while remaining_x or remaining_y:
            if abs(remaining_x) <= max_step and abs(remaining_y) <= max_step:
                step_x, step_y = remaining_x, remaining_y
            else:
                ratio = random.uniform(0.45, 0.8)
                step_x = round(max(-max_step, min(max_step, remaining_x * ratio)))
                step_y = round(max(-max_step, min(max_step, remaining_y * ratio)))

                if step_x == 0 and remaining_x != 0:
                    step_x = 1 if remaining_x > 0 else -1
                if step_y == 0 and remaining_y != 0:
                    step_y = 1 if remaining_y > 0 else -1

            await self._move_by_pixel(step_x, step_y)
            remaining_x -= step_x
            remaining_y -= step_y

            if remaining_x or remaining_y:
                await anyio.sleep(random.uniform(0.03, 0.12))
                if random.random() < 0.12:
                    await anyio.sleep(random.uniform(0.08, 0.25))

    async def click_current_pixel(self) -> None:
        """Click the current pixel on the page."""
        center_x, center_y = self.current_center_px
        target_x = center_x + random.uniform(-0.6, 0.6)
        target_y = center_y + random.uniform(-0.6, 0.6)
        approach_x = target_x + random.uniform(-6.0, 6.0)
        approach_y = target_y + random.uniform(-6.0, 6.0)

        await self.page.mouse.up(button="left")
        await self.page.mouse.move(approach_x, approach_y, steps=random.randint(4, 10))
        await anyio.sleep(random.uniform(0.02, 0.09))
        await self.page.mouse.move(target_x, target_y, steps=random.randint(2, 6))

        if random.random() < 0.35:
            await anyio.sleep(random.uniform(0.01, 0.04))
            await self.page.mouse.move(
                target_x + random.uniform(-0.8, 0.8),
                target_y + random.uniform(-0.8, 0.8),
                steps=random.randint(1, 3),
            )
            await self.page.mouse.move(target_x, target_y, steps=random.randint(1, 3))

        await anyio.sleep(random.uniform(0.015, 0.07))
        await self.page.mouse.down(button="left")
        await anyio.sleep(random.uniform(0.03, 0.11))
        await self.page.mouse.up(button="left")
        await anyio.sleep(random.uniform(0.01, 0.05))


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
            raise ElementNotFound("No paint button found on the page")

        logger.debug(f"Found paint button: {paint_btn!r}")
        await paint_btn.click()
        logger.info("Clicked paint button")

    @override
    async def close(self) -> None:
        btns = await self.page.query_selector_all(".w-full > .relative > .items-center > .btn.btn-circle.btn-sm")
        if not btns:
            logger.warning("No close button found on the paint panel")
            return
        close_btn = btns[-1]
        logger.debug(f"Found close button: {close_btn!r}")
        await close_btn.click()
        logger.info("Closed paint panel")

    async def select_color(self, color_id: int) -> None:
        color_btn = await self.page.wait_for_selector(f"#color-{color_id}", timeout=5_000, state="visible")
        if color_btn is None:
            raise ElementNotFound(f"Color button with ID {color_id} not found on the page")

        logger.debug(f"Found color button: {color_btn!r}")
        await color_btn.click()
        logger.opt(colors=True).debug(f"Selected color <g>{COLORS_NAME[color_id]}</>(id=<c>{color_id}</>)")

    async def captcha_exists(self) -> bool:
        return await self.page.query_selector("h-captcha") is not None

    async def submit(self) -> None:
        selector = f"#{self._btn_id}"
        btn = await self.page.query_selector(selector)
        if btn is None:
            raise ElementNotFound("Submit button not found, is the injected script broken?")

        logger.opt(colors=True).debug(f"Found submit button <c>{selector}</>: {escape_tag(repr(btn))}")
        await btn.click()
        logger.info("Clicked submit button")

        logger.debug("Waiting for submit to complete...")
        try:
            await self.page.wait_for_selector(selector, timeout=10_000, state="detached")
        except _pw_timeout_error():
            logger.warning("Submit button still present after timeout")
        else:
            logger.info("Submit completed")
            return

        if await self.captcha_exists():
            logger.warning("Captcha detected after clicking submit, manual intervention is required")
            await self.wait_for_captcha_resolved()

        logger.debug("Waiting for submit to complete after captcha resolution...")
        try:
            await self.page.wait_for_selector(selector, timeout=10_000, state="detached")
        except _pw_timeout_error():
            logger.warning("Submit button still present after captcha resolution")
        else:
            logger.info("Submit completed after captcha resolution")

    async def wait_for_captcha_resolved(self) -> None:
        from app.utils import toast

        toast.notify(APP_NAME, "检测到验证码，请打开浏览器完成验证后继续。", duration=toast.Duration.Long)
        while await self.captcha_exists():
            logger.warning("Captcha still present, waiting...")
            await anyio.sleep(5)


@functools.cache
def _pw_timeout_error() -> type[Exception]:
    from playwright._impl._errors import TimeoutError as PlaywrightTimeoutError

    return PlaywrightTimeoutError
