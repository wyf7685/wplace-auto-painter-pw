import abc
import contextlib
import functools
import hashlib
import json
import math
import random
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self, override

import anyio
import anyio.to_thread
from bot7685_ext.wplace.consts import COLORS_NAME
from pydantic import SecretStr

from app.browser import get_browser, get_persistent_context
from app.config import Config
from app.const import APP_NAME, USER_CONTEXT_DIR, assets
from app.exception import ElementNotFound, FetchFailed
from app.log import escape_tag, logger
from app.schemas import UserConfig, WplaceCredentials, WplaceUserInfo
from app.utils import Highlight, logger_wrapper

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from playwright.async_api import BrowserContext, ConsoleMessage, Page
else:
    ConsoleMessage = Any

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


class WplacePage:
    page: Page

    def __init__(self, user: UserConfig, key: str) -> None:
        self.user = user
        self.log = logger_wrapper(self.user.identifier)
        self._key = key
        self._btn_id = f"btn-{key}"
        self.has_captcha = False
        self.captcha_resolved = anyio.Event()

    @property
    def user_data_dir(self) -> Path:
        return USER_CONTEXT_DIR / hashlib.sha256(self.user.identifier.encode()).hexdigest()[:16]

    @classmethod
    @contextlib.asynccontextmanager
    async def create(cls, user: UserConfig, script_data: list[Any]) -> AsyncGenerator[Self]:
        self = cls(user, script_data[0])
        await self.notify_open_browser()

        async with get_persistent_context(
            user_data_dir=self.user_data_dir,
            viewport={"width": 1280, "height": 720},
        ) as context:
            context.on("console", self._on_console_log)
            await context.add_init_script(assets.page_init())
            await context.add_init_script(assets.paint_btn(script_data))
            await context.add_cookies(self.user.credentials.to_pw_cookies())
            self.log.debug(f"Using paint button ID: <c>{escape_tag(self._btn_id)}</>")

            async with await context.new_page() as page:
                for _page in filter(lambda p: p is not page, context.pages):
                    await _page.close()

                await page.goto("https://wplace.live/", timeout=60_000, wait_until="domcontentloaded")

                try:
                    await page.wait_for_selector(PAINT_BTN_SELECTOR, timeout=10_000, state="visible")
                    await page.wait_for_selector(f"#{self._btn_id}", timeout=10_000, state="attached")
                except _pw_timeout_error() as e:
                    raise ElementNotFound(
                        "Required buttons not found on the page, is the injected script broken?"
                    ) from e

                self.page = page
                try:
                    yield self
                finally:
                    del self.page

    async def notify_open_browser(self) -> None:
        from app.utils import toast

        self.log.debug("Sending notification for opening browser...")
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
            self.log.info("Toast timed out or dismissed, proceeding to open browser.")

    def _on_console_log(self, msg: ConsoleMessage) -> None:
        if not msg.text.startswith(self._key):
            return

        topic, message = msg.text.removeprefix(self._key).lstrip().split(" ", maxsplit=1)
        match topic:
            case "version":
                self.log.info(f"WPlace Version: <y>{escape_tag(message)}</>")
            case "submit" if message.startswith("success"):
                self.log.success("Paint submit <g>success</>")
            case "submit" if message.startswith("error"):
                error_msg = message.removeprefix("error").lstrip()
                self.log.error(f"Paint submit <r>error</>: <r>{escape_tag(error_msg)}</>")
            case "paint":
                data = message.strip()
                with contextlib.suppress(Exception):
                    data = json.loads(data)
                self.log.debug(f"Paint Response: {Highlight.apply(data)}")

                match data:
                    case {"error": "challenge-required"}:
                        self.log.warning("Captcha challenge detected during paint submit")
                        self.has_captcha = True
                    case {"painted": int(painted)}:
                        self.log.info(f"Painted pixel count: <g>{painted}</>")
                        self.has_captcha = False
                        self.captcha_resolved.set()

    async def find_and_close_modal(self) -> None:
        if modal := await self.page.query_selector(".modal[open]"):
            self.log.info("Found modal dialog")
            for el in await modal.query_selector_all("button.btn"):
                if await el.text_content() == "Close":
                    await el.click()
                    self.log.info("Closed modal dialog")
                    return
            self.log.warning("No Close button found in modal dialog")

    @contextlib.asynccontextmanager
    async def open_paint_panel(self) -> AsyncGenerator[PaintPanel]:
        await self.find_and_close_modal()
        async with PaintPanel(self, self._btn_id) as panel:
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
        target_x = center_x - dx * 7.65
        target_y = center_y - dy * 7.65
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
    def __init__(self, wplace_page: WplacePage) -> None:
        self.wplace_page = wplace_page
        self.page = wplace_page.page
        self.log = wplace_page.log

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
    def __init__(self, wplace_page: WplacePage, btn_id: str) -> None:
        super().__init__(wplace_page)
        self._btn_id = btn_id

    @override
    async def open(self) -> None:
        paint_btn = await self.page.query_selector(PAINT_BTN_SELECTOR)
        if paint_btn is None:
            raise ElementNotFound("No paint button found on the page")

        self.log.debug("Found paint button")
        await paint_btn.click()
        self.log.info("Clicked paint button")

    @override
    async def close(self) -> None:
        btns = await self.page.query_selector_all(".w-full > .relative > .items-center > .btn.btn-circle.btn-sm")
        if not btns:
            self.log.warning("No close button found on the paint panel")
            return
        close_btn = btns[-1]
        self.log.debug("Found close button")
        await close_btn.click()
        self.log.info("Closed paint panel")

    async def select_color(self, color_id: int) -> None:
        color_btn = await self.page.wait_for_selector(f"#color-{color_id}", timeout=5_000, state="visible")
        if color_btn is None:
            raise ElementNotFound(f"Color button with ID {color_id} not found on the page")

        self.log.debug("Found color button")
        await color_btn.click()
        self.log.debug(f"Selected color <g>{COLORS_NAME[color_id]}</>(id=<c>{color_id}</>)")

    async def submit(self) -> None:
        selector = f"#{self._btn_id}"
        btn = await self.page.query_selector(selector)
        if btn is None:
            raise ElementNotFound("Submit button not found, is the injected script broken?")

        self.log.debug(f"Found submit button <c>{selector}</>: {escape_tag(repr(btn))}")
        await btn.click()
        self.log.info("Clicked submit button")

        self.log.debug("Waiting for submit to complete...")
        try:
            await self.page.wait_for_selector(selector, timeout=10_000, state="detached")
        except _pw_timeout_error():
            self.log.warning("Submit button still present after timeout")
        else:
            self.log.info("Submit completed")
            return

        await self.check_captcha()

        self.log.debug("Waiting for submit to complete after captcha resolution...")
        try:
            await self.page.wait_for_selector(selector, timeout=5_000, state="detached")
        except _pw_timeout_error():
            self.log.warning("Submit button still present after captcha resolution")
        else:
            self.log.info("Submit completed after captcha resolution")

    async def check_captcha(self) -> None:
        if not self.wplace_page.has_captcha:
            return

        self.log.warning("Captcha detected after clicking submit, manual intervention is required")

        from app.utils import toast

        self.log.debug("Notifying user to resolve captcha...")
        toast.notify(APP_NAME, "检测到验证码，请打开浏览器完成验证后继续。", duration=toast.Duration.Long)

        self.log.info("Waiting for captcha to be resolved...")
        await self.wplace_page.captcha_resolved.wait()


@functools.cache
def _pw_timeout_error() -> type[Exception]:
    from playwright._impl._errors import TimeoutError as PlaywrightTimeoutError

    return PlaywrightTimeoutError
