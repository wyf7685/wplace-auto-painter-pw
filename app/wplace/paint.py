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
from app.exception import PaintFinished, PaintRequestFailed, ShouldQuit, TokenExpired
from app.log import escape_tag, log_prefix_width, logger
from app.schemas import TemplateConfig, WplaceUserInfo
from app.utils import Highlight, draw_ansi, is_token_expired, logger_wrapper
from app.wplace.page import CANVAS_ZOOM, UserContext, WplacePage
from app.wplace.purchase import process_purchase
from app.wplace.resolver import resolve_js
from app.wplace.template import calc_template_diff

logger = logger.opt(colors=True)
# Colors currently being painted, so concurrent users don't fight over the same
# ones. Guarded by `COLORS_CLAIMER_LOCK`; a plain set avoids the task-ownership
# semantics of `anyio.Lock`, which would reject a re-claim from the same task.
COLORS_CLAIMER_LOCK = anyio.Lock()
CLAIMED_COLORS: set[ColorName] = set()


class Pixel(NamedTuple):
    x: int
    y: int
    color: int


class Painter:
    def __init__(self, user: UserConfig) -> None:
        self.user = user
        self.log = logger_wrapper(self.user.identifier)
        self._context: UserContext | None = None
        # Upper bound on pixels per cycle. Unbounded except for the captcha-bait
        # first cycle of each context; see `run`.
        self._paint_charge_limit = float("inf")
        self._user_info_cache: tuple[WplaceUserInfo, datetime] | None = None

    @property
    def context(self) -> UserContext:
        if self._context is None:
            raise RuntimeError("UserContext is not available outside of the painting loop.")
        return self._context

    async def get_user_info(self) -> WplaceUserInfo:
        if self._user_info_cache is not None:
            user_info, fetched_at = self._user_info_cache
            if datetime.now() - fetched_at < timedelta(seconds=30):
                self.log.debug(f"Using cached user info: {Highlight.apply(user_info)}")
                return user_info

        user_info = await self.context.fetch_user_info()
        fetched_at = datetime.now()
        self._user_info_cache = (user_info, fetched_at)
        self.log.debug(f"Fetched user info: {Highlight.apply(user_info)}")

        self.log.info(f"Current droplets: 💧 <y>{user_info.droplets}</>")
        charges = user_info.charges
        remaining_secs = charges.remaining_secs()
        recover_time = (fetched_at + timedelta(seconds=remaining_secs)).strftime("%Y-%m-%d %H:%M:%S")
        self.log.info(f"Current charge: 🎨 <y>{charges.count:.2f}</>/<y>{charges.max}</> ")
        self.log.info(f"Remaining: ⏱️ <y>{remaining_secs:.2f}</>s, recovers at <g>{recover_time}</>")
        return user_info

    @contextlib.asynccontextmanager
    async def claim_painting_color(self, names: Iterable[ColorName]) -> AsyncGenerator[frozenset[ColorName]]:
        """Claim as many of `names` as are still free, yielding the ones actually held.

        Claiming never blocks: a color taken by another painter since it was
        selected is dropped rather than waited on, so a slow peer cannot stall
        this cycle. `COLORS_CLAIMER_LOCK` keeps the batch acquisition atomic.
        """
        claimed: set[ColorName] = set()
        try:
            async with COLORS_CLAIMER_LOCK:
                for name in names:
                    if name in CLAIMED_COLORS:
                        self.log.debug(f"Color claimed by another painter, skipping: <g>{name}</>")
                        continue
                    self.log.debug(f"Claimed color: <g>{name}</>")
                    claimed.add(name)
                CLAIMED_COLORS.update(claimed)
            yield frozenset(claimed)
        finally:
            # No lock: set mutation is atomic under the event loop, and awaiting
            # here would fail during cancellation.
            CLAIMED_COLORS.difference_update(claimed)

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
                if entry.count > 0 and entry.name in user_info.own_colors and entry.name not in CLAIMED_COLORS:
                    self.log.info(f"Select color: <g>{entry.name}</> with <y>{entry.count}</> pixels to paint.")
                    entries.append(entry)
                total = sum(e.count for e in entries)
                if total >= user_info.charges.count * 0.9 or total >= self._paint_charge_limit:
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
        pixels_to_paint = int(min(charges, len(pixels), self._paint_charge_limit))
        if self.user.max_paint_charges is not None:
            pixels_to_paint = min(pixels_to_paint, int(self.user.max_paint_charges * random.uniform(0.95, 1.05)))
        if pixels_to_paint <= 0:
            self.log.warning("Not enough pixels to paint.")
            return None
        self.log.info(f"Preparing to paint <y>{pixels_to_paint}</> pixels...")
        return pixels[:pixels_to_paint]

    async def paint_pixels(self, user_info: WplaceUserInfo) -> bool:
        resolved_js = await resolve_js()
        self.log.info(f"Resolved paint functions: {Highlight.apply(resolved_js)}")

        if (selected := await self.select_paint_color(user_info)) is None:
            raise PaintFinished("No colors available to paint")
        template, entries = selected
        base = template.get_coords()[0]

        self.log.info("Template preview:")
        draw_ansi(
            template.load_im(),
            write_line=self.log.info,
            prefix_length=log_prefix_width(__name__, "INFO", self.user.identifier),
        )

        async with self.claim_painting_color(entry.name for entry in entries) as claimed:
            if not claimed:
                self.log.warning("All selected colors were claimed by other painters, skipping this cycle.")
                return False

            entries = [entry for entry in entries if entry.name in claimed]
            pixels = await self.prepare_pixels(entries, int(user_info.charges.count))
            if not pixels:
                return False

            script_data = [
                uuid.uuid4().hex[:8],
                [[*base.offset(x, y).as_dtuple(), color_id] for x, y, color_id in pixels],
                resolved_js,
                [*base.offset(*pixels[0][:2]).to_lat_lon()],
                CANVAS_ZOOM,
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

        return True

    async def _run_once(self) -> float:
        self.log.info("Starting painting cycle...")
        self.log.debug(f"User config: {Highlight.apply(self.user)}")

        if is_token_expired(self.user.credentials.token.get_secret_value()):
            self.log.warning("Token expired, stopping paint loop.")
            raise TokenExpired("Token expired")

        user_info = await self.get_user_info()
        painted = False
        if user_info.charges.count >= self.user.min_paint_charges:
            painted = await self.paint_pixels(user_info)
            if painted:
                # Painting mutates server-side charges; force a fresh snapshot.
                self._user_info_cache = None
                user_info = await self.get_user_info()
            else:
                self.log.warning("Nothing was painted this cycle.")
        else:
            self.log.warning("Not enough charges to paint pixels.")
            self.log.warning(f"Minimum required charges: <y>{self.user.min_paint_charges}</>")

        if self.user.auto_purchase is not None:
            self.log.info(f"Checking auto-purchase: {Highlight.apply(self.user.auto_purchase)}")
            if await process_purchase(self.user, user_info):
                self.log.info("Purchase completed, refetching user info...")
                # A successful purchase mutates charges/droplets; do not reuse stale data.
                self._user_info_cache = None
                user_info = await self.get_user_info()
            else:
                self.log.info("No purchase made.")

        # Computed once from the freshest user info, after any purchase.
        # Painted: wait for a meaningful refill. Otherwise either charges were
        # short (wait until `min_paint_charges` is back) or something blocked the
        # cycle with charges untouched (`secs_until` is 0, so the floor applies
        # and we retry in ~10min instead of busy-spinning).
        wait_secs = (
            min(
                60 * 60 * 4 + random.uniform(-10, 10) * 60,  # 4hrs +/- 10min
                user_info.charges.remaining_secs() * random.uniform(0.85, 0.95),
            )
            if painted
            else max(
                60 * 10 + random.uniform(-2, 2) * 60,  # 10min +/- 2min
                user_info.charges.secs_until(self.user.min_paint_charges),
            )
        )

        # Only loop straight into another cycle when this one actually painted;
        # otherwise we would busy-spin against whatever blocked it.
        if painted and user_info.charges.count >= self.user.min_paint_charges:
            self.log.info(
                f"Still have enough charges to paint (>=<y>{self.user.min_paint_charges}</>), continuing immediately."
            )
            return 0

        if painted and self.user.selected_area is not None:
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
        except ShouldQuit as error:
            self.log.warning(f"{type(error).__name__}: {error}; exiting paint loop")
            return None
        except PaintRequestFailed:
            wait_secs = random.uniform(5, 10) * 60
            self.log.exception("Paint request failed")
            self.log.info(f"Sleeping for <y>{wait_secs / 60:.2f}</> minutes before retrying...")
        except httpx.RequestError:
            wait_secs = random.uniform(0.5, 1.5) * 60  # 0.5-1.5 minutes
            self.log.exception("Request error occurred")
            self.log.info(f"Maybe network issue? Sleeping for <y>{wait_secs / 60:.2f}</> minutes before retrying...")
        except Exception:
            wait_secs = random.uniform(1, 3) * 60  # 1-3 minutes
            self.log.exception("An error occurred")
            self.log.info(f"Sleeping for <y>{wait_secs / 60:.2f}</> minutes before retrying...")
        return wait_secs

    async def run(self) -> None:
        while True:
            async with UserContext.create(self.user) as self._context:
                # Deliberately paint a tiny batch on the first cycle of a fresh
                # context: Cloudflare tends to challenge the first submit from a
                # new browser context, and `PaintPanel.submit` blocks on manual
                # resolution. Spending the challenge on ~10 pixels means the user
                # is prompted once, up front, while the bulk batches that follow
                # reuse the same context and run unattended. Sizing this batch by
                # `max_paint_charges` instead would put a full unattended run
                # behind that prompt.
                self._paint_charge_limit = random.uniform(5, 15)
                try:
                    wait_secs = await self._run_once_with_catch()
                finally:
                    self._paint_charge_limit = float("inf")
                if wait_secs is None:
                    return

                # A positive wait from the first cycle is a real refill or retry
                # delay; do not start a full-size cycle before it expires.
                if wait_secs <= 0:
                    await anyio.sleep(random.uniform(0.5, 2.5))

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
