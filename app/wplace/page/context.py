import contextlib
import functools
import hashlib
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

import anyio
import anyio.to_thread
from pydantic import SecretStr

from app.browser import get_browser, get_persistent_context
from app.config import Config
from app.const import APP_NAME, USER_CONTEXT_DIR, assets
from app.exception import FetchFailed
from app.log import logger
from app.schemas import UserConfig, WplaceCredentials, WplaceUserInfo
from app.utils import Highlight, logger_wrapper

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from playwright.async_api import BrowserContext, ConsoleMessage, Page
else:
    ConsoleMessage = Any

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


class UserContext:
    def __init__(self, user: UserConfig) -> None:
        self.user = user
        self.log = logger_wrapper(self.user.identifier)
        self._context = None
        self._stack = contextlib.AsyncExitStack()
        self._context_lock = anyio.Lock()

    @property
    def user_data_dir(self) -> Path:
        return USER_CONTEXT_DIR / hashlib.sha256(self.user.identifier.encode()).hexdigest()[:16]

    @classmethod
    @contextlib.asynccontextmanager
    async def create(cls, user: UserConfig) -> AsyncGenerator[Self]:
        self = cls(user)

        try:
            async with self._stack:
                yield self
        finally:
            self.log.debug("Closing browser context...")
            self._context = None

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

    async def get_context(self) -> BrowserContext:
        async with self._context_lock:
            if self._context is not None:
                return self._context

            await self.notify_open_browser()
            cm = get_persistent_context(
                user_data_dir=self.user_data_dir,
                viewport={"width": 1280, "height": 720},
                user_agent=USER_AGENT,
            )
            context = await self._stack.enter_async_context(cm)
            await context.add_init_script(assets.page_init())
            await context.add_cookies(self.user.credentials.to_pw_cookies())
            self.log.success("Browser context created")
            self._context = context

        return self._context

    @contextlib.asynccontextmanager
    async def new_page(self, close_others: bool = True) -> AsyncGenerator[Page]:
        context = await self.get_context()
        page = await context.new_page()
        self.log.debug("New page created")

        if close_others:
            for _page in filter(lambda p: p is not page, context.pages):
                with contextlib.suppress(Exception):
                    await _page.close()

        try:
            yield page
        finally:
            if close_others:
                # avoid closing context
                await context.new_page()
            await page.close()

    async def fetch_user_info(self) -> WplaceUserInfo:
        credentials = self.user.credentials

        async with (
            _headless_context(credentials)
            if self._context is None
            else contextlib.nullcontext(self._context) as context,
            await context.new_page() as page,
        ):
            resp = await page.goto("https://backend.wplace.live/me", wait_until="networkidle")
            if not resp:
                raise FetchFailed("Failed to fetch user info")
            text = await resp.text()
            cookies = await context.cookies()

        update = False
        for ck in filter(lambda ck: ck.get("domain", "").endswith("wplace.live"), cookies):
            match ck:
                case {"name": "j", "value": str(ck_val)} if ck_val != credentials.token.get_secret_value():
                    credentials.token = SecretStr(ck_val)
                    update = True
                case {"name": "cf_clearance", "value": str(ck_val)} if (
                    credentials.cf_clearance is None or ck_val != credentials.cf_clearance.get_secret_value()
                ):
                    credentials.cf_clearance = SecretStr(ck_val)
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
