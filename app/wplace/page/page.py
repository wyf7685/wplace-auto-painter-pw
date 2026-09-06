import asyncio
import contextlib
import json
import math
import random
from collections.abc import Sequence
from itertools import pairwise
from typing import TYPE_CHECKING, Any, Self

import anyio

from app.browser import pw_timeout_error
from app.const import assets
from app.exception import ElementNotFound, PaintAccountBanned, PaintRequestBlocked, PaintRequestFailed, TokenExpired
from app.log import escape_tag
from app.utils import Highlight

from .context import UserContext
from .panel import PaintPanel

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from playwright.async_api import ConsoleMessage, ElementHandle, Page, Response
else:
    ConsoleMessage = ElementHandle = Page = Response = Any

PAINT_BTN_SELECTOR = ".disable-pinch-zoom > div.absolute .btn.btn-primary.btn-lg"
PAINT_REQUEST_URL = "https://backend.wplace.live/paint"

# Map zoom level the injected script writes into `localStorage.location`. Passed
# through `script_data`, so this stays the single source of truth for both sides.
CANVAS_ZOOM = 15

# CSS pixels covered by one canvas pixel at `CANVAS_ZOOM`, measured against the
# live site. Only valid for `CANVAS_ZOOM`: every mouse offset below is scaled by
# it, so a stale value silently paints at the wrong coordinates. Re-measure if
# `CANVAS_ZOOM` changes or wplace alters its map projection.
CANVAS_PX_PER_PIXEL = 7.65


class WplacePage:
    page: Page

    def __init__(self, context: UserContext, key: str) -> None:
        self.log = context.log
        self._key = key
        self._btn_id = f"btn-{key}"
        self.has_captcha = False
        self.captcha_resolved = anyio.Event()
        self._paint_response_tasks: set[asyncio.Task[None]] = set()
        self._paint_error: Exception | None = None
        # Set only after the injected script completes the whole batch.
        self._submit_succeeded = False

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
            page.on("response", self._on_response)
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
                await self.wait_for_paint_responses()
                del self.page

    def _on_console_log(self, msg: ConsoleMessage) -> None:
        if not msg.text.startswith(self._key):
            return

        topic, _, message = msg.text.removeprefix(self._key).lstrip().partition(" ")
        message = message.strip()
        match topic:
            case "version":
                self.log.info(f"WPlace Version: <y>{escape_tag(message)}</>")
            case "submit-success":
                self.log.success("Paint submit <g>success</>")
                self._submit_succeeded = True
                self.has_captcha = False
                self.captcha_resolved.set()
            case "submit-error":
                self.log.error(f"Paint submit <r>error</>: <r>{escape_tag(message)}</>")
                if self._paint_error is None:
                    self._record_paint_error(PaintRequestFailed(message))
                if self.has_captcha:
                    self.log.warning("Challenge flow ended without a successful paint response")
                self.captcha_resolved.set()

    def _on_response(self, response: Response) -> None:
        if response.url != PAINT_REQUEST_URL or response.request.method != "POST":
            return

        task = asyncio.create_task(self._read_paint_response(response))
        self._paint_response_tasks.add(task)

    async def _read_paint_response(self, response: Response) -> None:
        if response.ok:
            # A batch may issue multiple requests; submit-success is the batch-level signal.
            return

        headers = response.headers
        if response.status == 401 or headers.get("x-block-reason") or headers.get("cf-mitigated"):
            self._handle_paint_response(response, {})
            return

        try:
            with anyio.fail_after(10):
                text = await response.text()
        except TimeoutError:
            self._record_paint_error(
                PaintRequestFailed(
                    f"Timed out reading paint response body (HTTP {response.status})",
                    status=response.status,
                )
            )
            return
        except Exception:
            self.log.exception("Failed to read paint response")
            return

        data: object = text
        with contextlib.suppress(Exception):
            data = json.loads(text)
        self.log.debug(f"Paint Response: {Highlight.apply(data)}")
        self._handle_paint_response(response, data)

    def _handle_paint_response(self, response: Response, data: object) -> None:
        if self._submit_succeeded:
            return
        headers = response.headers
        block_reason = headers.get("x-block-reason", "").lower()
        if block_reason in {"integrity", "tor"}:
            self._record_paint_error(PaintRequestBlocked(f"Paint request blocked by server policy: {block_reason}"))
            return

        if response.status == 401:
            self._record_paint_error(TokenExpired("Authentication token expired during paint submit"))
            return

        if headers.get("cf-mitigated", "").lower() == "challenge" or (isinstance(data, str) and "html" in data.lower()):
            self.log.warning("Received a Cloudflare challenge during paint submit")
            self.has_captcha = True
            return

        payload: dict[str, object] = data if isinstance(data, dict) else {}
        code = payload.get("error")
        if code == "challenge-required":
            tier = payload.get("tier")
            self.log.warning(f"Captcha challenge detected during paint submit, tier={tier!r}")
            self.has_captcha = True
            return
        if code == "verification-required":
            self.log.warning("Additional fingerprint verification required during paint submit")
            return
        if code == "timeout":
            duration_ms = payload.get("durationMs")
            suffix = f" (durationMs={duration_ms})" if isinstance(duration_ms, int | float) else ""
            self._record_paint_error(
                PaintAccountBanned(f"Paint request returned timeout; treating account as banned{suffix}")
            )
            return

        if isinstance(code, str):
            error = PaintRequestFailed(
                f"Paint request failed: {code}",
                status=response.status,
                code=code,
            )
        else:
            error = PaintRequestFailed(
                f"Paint request failed with HTTP {response.status}: {data!r}",
                status=response.status,
            )
        self._record_paint_error(error)

    def _record_paint_error(self, error: Exception) -> None:
        self._paint_error = error
        if not self.captcha_resolved.is_set():
            self.captcha_resolved.set()

    async def wait_for_paint_responses(self) -> None:
        while self._paint_response_tasks:
            tasks = tuple(self._paint_response_tasks)
            await asyncio.gather(*tasks)
            self._paint_response_tasks.difference_update(tasks)

    def raise_for_paint_error(self) -> None:
        if self._paint_error is not None:
            raise self._paint_error

    def ensure_submit_succeeded(self) -> None:
        if not self._submit_succeeded:
            raise PaintRequestFailed("Paint submit did not report success")

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
        target_x = center_x - dx * CANVAS_PX_PER_PIXEL
        target_y = center_y - dy * CANVAS_PX_PER_PIXEL
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

    async def paint_space_drag(self, offsets: Sequence[tuple[int, int]]) -> None:
        """Queue a continuous pixel stroke by holding Space while moving the pointer."""
        if not offsets:
            raise ValueError("offsets cannot be empty")
        for previous, current in pairwise(offsets):
            if max(abs(current[0] - previous[0]), abs(current[1] - previous[1])) > 1:
                raise ValueError("space drag offsets must be adjacent")

        center_x, center_y = self.current_center_px

        def screen_position(offset: tuple[int, int]) -> tuple[float, float]:
            return (
                center_x + offset[0] * CANVAS_PX_PER_PIXEL,
                center_y + offset[1] * CANVAS_PX_PER_PIXEL,
            )

        first_x, first_y = screen_position(offsets[0])
        await self.page.mouse.up(button="left")
        await self.page.mouse.move(first_x, first_y, steps=random.randint(3, 7))
        await anyio.sleep(random.uniform(0.02, 0.08))
        await self.page.keyboard.down("Space")
        try:
            for offset in offsets[1:]:
                target_x, target_y = screen_position(offset)
                await self.page.mouse.move(target_x, target_y, steps=random.randint(2, 4))
                await anyio.sleep(random.uniform(0.01, 0.04))
        finally:
            with anyio.CancelScope(shield=True):
                await self.page.keyboard.up("Space")
        await anyio.sleep(random.uniform(0.03, 0.12))

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
