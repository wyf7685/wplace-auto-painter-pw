import contextlib
import random
import uuid
from collections.abc import AsyncGenerator, Iterable
from datetime import datetime, timedelta
from typing import NamedTuple

import anyio
import httpx
from bot7685_ext.wplace import ColorEntry, group_adjacent
from bot7685_ext.wplace.consts import COLORS_NAME, ColorName

from app.config import Config, UserConfig
from app.exception import PaintFinished, ShouldQuit, TokenExpired
from app.log import escape_tag, logger
from app.schemas import TemplateConfig, WplaceUserInfo
from app.utils import Highlight, draw_ansi, is_token_expired, logger_wrapper
from app.wplace.fingerprint import generate_fingerprint
from app.wplace.page import UserContext, WplacePage
from app.wplace.purchase import do_purchase
from app.wplace.resolver import resolve_js
from app.wplace.template import calc_template_diff

logger = logger.opt(colors=True)
COLORS_CLAIMER_LOCK = anyio.Lock()
COLORS_LOCK: dict[ColorName, anyio.Lock] = {name: anyio.Lock() for name in COLORS_NAME.values()}


class Pixel(NamedTuple):
    x: int
    y: int
    color: int


class Painter:
    def __init__(self, user: UserConfig) -> None:
        self.user = user
        self.log = logger_wrapper(self.user.identifier)
        self._context: UserContext | None = None

    @property
    def context(self) -> UserContext:
        if self._context is None:
            raise RuntimeError("UserContext is not available outside of the painting loop.")
        return self._context

    async def get_user_info(self) -> WplaceUserInfo:
        user_info = await self.context.fetch_user_info()
        self.log.debug(f"Fetched user info: {Highlight.apply(user_info)}")
        self.log.info(f"Current droplets: 💧 <y>{user_info.droplets}</>")
        charges = user_info.charges
        remaining_secs = charges.remaining_secs()
        recover_time = (datetime.now() + timedelta(seconds=remaining_secs)).strftime("%Y-%m-%d %H:%M:%S")
        self.log.info(f"Current charge: 🎨 <y>{charges.count:.2f}</>/<y>{charges.max}</> ")
        self.log.info(f"Remaining: ⏱️ <y>{remaining_secs:.2f}</>s, recovers at <g>{recover_time}</>")
        return user_info

    @contextlib.asynccontextmanager
    async def claim_painting_color(self, names: Iterable[ColorName]) -> AsyncGenerator[None]:
        async with contextlib.AsyncExitStack() as stack:
            async with COLORS_CLAIMER_LOCK:
                for name in names:
                    self.log.debug(f"Attempting to claim color: <g>{name}</>")
                    await stack.enter_async_context(COLORS_LOCK[name])
            yield

    async def select_paint_color(self, user_info: WplaceUserInfo) -> tuple[TemplateConfig, list[ColorEntry]] | None:
        def sort_key(entry: ColorEntry) -> tuple[int, ...]:
            return (
                -(
                    self.user.preferred_colors.index(entry.name)
                    if entry.name in self.user.preferred_colors
                    else len(self.user.preferred_colors) + 1
                ),
                entry.is_paid,
                entry.name in user_info.own_colors,
                entry.count,
            )

        async def select(template: TemplateConfig) -> list[ColorEntry] | None:
            diff = await calc_template_diff(template, include_pixels=True)
            entries: list[ColorEntry] = []
            for entry in sorted(diff, key=sort_key, reverse=True):
                if entry.count > 0 and entry.name in user_info.own_colors and not COLORS_LOCK[entry.name].locked():
                    self.log.info(f"Select color: <g>{entry.name}</> with <y>{entry.count}</> pixels to paint.")
                    entries.append(entry)
                if sum(e.count for e in entries) >= user_info.charges.count * 0.9:
                    break
            return entries or None

        if self.user.selected_area is not None:
            self.log.info(f"Using selected area for painting: <g>{self.user.selected_area}</>")
            template = self.user.template.crop(self.user.selected_area)
            if entries := await select(template):
                return template, entries

            self.log.warning("No available colors to paint in the selected area, falling back to full template.")

        if entries := await select(self.user.template):
            return self.user.template, entries

        self.log.warning("No available colors to paint the template.")
        return None

    async def prepare_pixels(self, entries: list[ColorEntry], charges: int) -> list[Pixel] | None:
        self.log.info("Grouping pixels...")
        groups = await group_adjacent([(x, y, e.id) for e in entries for x, y in e.pixels])
        self.log.info(f"Found <y>{len(groups)}</> groups of adjacent pixels to paint.")
        colors_rank = self.user.preferred_colors_rank()
        pixels = sorted((Pixel(*p) for g in groups for p in g), key=lambda p: colors_rank[p[2]])
        pixels_to_paint = min(charges, len(pixels))
        if self.user.max_paint_charges is not None:
            pixels_to_paint = min(pixels_to_paint, self.user.max_paint_charges)
        if pixels_to_paint <= 0:
            self.log.warning("Not enough pixels to paint.")
            return None
        self.log.info(f"Preparing to paint <y>{pixels_to_paint}</> pixels...")
        return pixels[:pixels_to_paint]

    async def paint_pixels(self, user_info: WplaceUserInfo) -> None:
        resolved_js = await resolve_js()
        self.log.info(f"Resolved paint functions: {Highlight.apply(resolved_js)}")

        if (selected := await self.select_paint_color(user_info)) is None:
            raise PaintFinished("No colors available to paint")
        template, entries = selected
        base = template.get_coords()[0]

        self.log.info("Template preview:")
        draw_ansi(template.load_im(), write_line=self.log.info, prefix_length=37 + len(self.user.identifier))

        async with self.claim_painting_color(entry.name for entry in entries):
            pixels = await self.prepare_pixels(entries, int(user_info.charges.count))
            if not pixels:
                return

            script_data = [
                uuid.uuid4().hex[:8],
                [[*base.offset(x, y).tuple(), color_id] for x, y, color_id in pixels],
                generate_fingerprint(self.user.identifier, len(pixels)),
                resolved_js,
                [*base.offset(*pixels[0][:2]).to_lat_lon()],
            ]

            async with WplacePage.create(self.context, script_data) as page:
                delay = random.uniform(3, 7)
                self.log.info(f"Waiting for <y>{delay:.2f}</> seconds before painting...")
                await anyio.sleep(delay)

                async with page.open_paint_panel() as paint:
                    prev = pixels[0]
                    await anyio.sleep(random.uniform(0.5, 1.5))
                    await paint.select_color(prev.color)
                    for curr in pixels:
                        if prev.color != curr.color:
                            await anyio.sleep(random.uniform(0.5, 1.5))
                            self.log.info(
                                f"Switching color: <g>{COLORS_NAME[prev.color]}</>(id=<c>{prev.color}</>) "
                                f"-> <g>{COLORS_NAME[curr.color]}</>(id=<c>{curr.color}</>)"
                            )
                            await paint.select_color(curr.color)
                            await anyio.sleep(random.uniform(0.5, 1.5))
                        await page.move_by_pixel(curr.x - prev.x, curr.y - prev.y)
                        await page.click_current_pixel()
                        prev = curr
                        if random.random() < 0.02:
                            idle_secs = random.uniform(0.5, 2.0)
                            self.log.debug(f"Taking a short break for <y>{idle_secs:.2f}</> seconds...")
                            await anyio.sleep(idle_secs)

                    delay = random.uniform(3, 7)
                    self.log.info(f"Waiting for <y>{delay:.2f}</> seconds before submitting...")
                    await anyio.sleep(delay)
                    await paint.submit()

    async def _run_once(self) -> float:
        self.log.info("Starting painting cycle...")
        self.log.debug(f"User config: {Highlight.apply(self.user)}")

        if is_token_expired(self.user.credentials.token.get_secret_value()):
            self.log.warning("Token expired, stopping paint loop.")
            raise TokenExpired("Token expired")

        user_info = await self.get_user_info()
        if should_paint := user_info.charges.count >= self.user.min_paint_charges:
            await self.paint_pixels(user_info)
            self.log.info("Painting completed, refetching user info...")
            user_info = await self.get_user_info()

            wait_secs = min(
                user_info.charges.remaining_secs() * random.uniform(0.85, 0.95),
                60 * 60 * 4 + random.uniform(-10, 10) * 60,
            )
        else:
            self.log.warning("Not enough charges to paint pixels.")
            self.log.warning(f"Minimum required charges: <y>{self.user.min_paint_charges}</>")
            wait_secs = max(600.0, user_info.charges.remaining_secs() - random.uniform(10, 20) * 60)

        if self.user.auto_purchase is not None:
            self.log.info(f"Checking auto-purchase: {Highlight.apply(self.user.auto_purchase)}")
            if await do_purchase(self.user, user_info):
                self.log.info("Purchase completed, refetching user info...")
                user_info = await self.get_user_info()
            else:
                self.log.info("No purchase made.")

            wait_secs = min(
                user_info.charges.remaining_secs() * random.uniform(0.85, 0.95),
                60 * 60 * 4 + random.uniform(-10, 10) * 60,
            )

        if user_info.charges.count >= self.user.min_paint_charges:
            self.log.info(
                f"Still have enough charges to paint (>=<y>{self.user.min_paint_charges}</>), continuing immediately."
            )
            return 0

        if should_paint and self.user.selected_area is not None:
            template = self.user.template.crop(self.user.selected_area)
            diff = await calc_template_diff(template, include_pixels=False)
            if diff := sorted(filter(lambda e: e.count, diff), key=lambda e: e.count, reverse=True)[:5]:
                self.log.info(f"Top {len(diff)} colors needed in selected area:")
                for idx, entry in enumerate(diff, 1):
                    self.log.info(f" {idx}. <g>{entry.name}</>: <y>{entry.count}</> pixels")
            else:
                self.log.warning("Selected area is fully painted, consider changing it.")

        wakeup_at = datetime.now() + timedelta(seconds=wait_secs)
        self.log.info(f"Sleeping for <y>{wait_secs / 60:.2f}</> minutes...")
        self.log.info(f"Next paint cycle at <g>{wakeup_at:%Y-%m-%d %H:%M:%S}</>.")
        return wait_secs

    async def _run_once_with_catch(self) -> float | None:
        try:
            wait_secs = await self._run_once()
        except ShouldQuit:
            self.log.warning("Received shutdown signal, exiting paint loop.", exception=True)
            return None
        except httpx.RequestError:
            wait_secs = random.uniform(0.5, 1.5) * 60
            self.log.exception("Request error occurred")
            self.log.info(f"Maybe network issue? Sleeping for <y>{wait_secs / 60:.2f}</> minutes before retrying...")
        except Exception:
            wait_secs = random.uniform(1, 3) * 60
            self.log.exception("An error occurred")
            self.log.info(f"Sleeping for <y>{wait_secs / 60:.2f}</> minutes before retrying...")
        return wait_secs

    async def run(self) -> None:
        while True:
            async with UserContext.create(self.user) as self._context:
                while True:
                    wait_secs = await self._run_once_with_catch()
                    if wait_secs is None:
                        return
                    if wait_secs > 0:
                        break

            self._context = None
            await anyio.sleep(max(wait_secs, 0))


async def setup_paint() -> None:
    async with anyio.create_task_group() as tg:
        for user in Config.load().users:
            logger.info(f"Starting paint loop for user: <lm>{escape_tag(user.identifier)}</>")
            tg.start_soon(Painter(user).run)
            await anyio.sleep(30)
