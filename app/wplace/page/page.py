import contextlib
import json
import math
import random
from typing import TYPE_CHECKING, Any, Self

import anyio

from app.browser import pw_timeout_error
from app.const import assets
from app.exception import ElementNotFound
from app.log import escape_tag
from app.utils import Highlight

from .context import UserContext
from .panel import PaintPanel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from playwright.async_api import ConsoleMessage, ElementHandle, Page
else:
    ConsoleMessage = Any

PAINT_BTN_SELECTOR = ".disable-pinch-zoom > div.absolute .btn.btn-primary.btn-lg"


class WplacePage:
    page: Page

    def __init__(self, context: UserContext, key: str) -> None:
        self.log = context.log
        self._key = key
        self._btn_id = f"btn-{key}"
        self.has_captcha = False
        self.captcha_resolved = anyio.Event()

    @property
    def submit_btn_selector(self) -> str:
        return f"#{self._btn_id}"

    @classmethod
    @contextlib.asynccontextmanager
    async def create(cls, context: UserContext, script_data: list[Any]) -> AsyncGenerator[Self]:
        self = cls(context, script_data[0])

        self.log.debug(f"Using paint button ID: <c>{escape_tag(self._btn_id)}</>")

        async with context.new_page() as page:
            page.on("console", self._on_console_log)
            await page.add_init_script(assets.paint_btn(script_data))
            await page.goto("https://wplace.live/", timeout=60_000, wait_until="domcontentloaded")

            try:
                await page.wait_for_selector(PAINT_BTN_SELECTOR, timeout=10_000, state="visible")
                await page.wait_for_selector(self.submit_btn_selector, timeout=10_000, state="attached")
            except pw_timeout_error() as e:
                raise ElementNotFound("Required buttons not found on the page, is the injected script broken?") from e

            self.page = page
            try:
                yield self
            finally:
                del self.page

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

    async def find_paint_button(self) -> ElementHandle:
        paint_btn = await self.page.query_selector(PAINT_BTN_SELECTOR)
        if paint_btn is None:
            raise ElementNotFound("No paint button found on the page")
        return paint_btn

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
        async with PaintPanel(self) as panel:
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
