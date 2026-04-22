from typing import TYPE_CHECKING, Self

from bot7685_ext.wplace.consts import COLORS_NAME

from app.browser import pw_timeout_error
from app.const import APP_NAME
from app.exception import ElementNotFound
from app.log import escape_tag

if TYPE_CHECKING:
    from .page import WplacePage


class PaintPanel:
    def __init__(self, wplace_page: WplacePage) -> None:
        self.wplace_page = wplace_page
        self.page = wplace_page.page
        self.log = wplace_page.log

    async def __aenter__(self) -> Self:
        await self.open()
        return self

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self.close()

    async def open(self) -> None:
        paint_btn = await self.wplace_page.find_paint_button()
        self.log.debug("Found paint button")
        await paint_btn.click()
        self.log.info("Clicked paint button")

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
        selector = self.wplace_page.submit_btn_selector
        btn = await self.page.query_selector(selector)
        if btn is None:
            raise ElementNotFound("Submit button not found, is the injected script broken?")

        self.log.debug(f"Found submit button <c>{selector}</>: {escape_tag(repr(btn))}")
        await btn.click()
        self.log.info("Clicked submit button")

        self.log.debug("Waiting for submit to complete...")
        try:
            await self.page.wait_for_selector(selector, timeout=10_000, state="detached")
        except pw_timeout_error():
            self.log.warning("Submit button still present after timeout")
        else:
            self.log.info("Submit completed")
            return

        await self.check_captcha()

        self.log.debug("Waiting for submit to complete after captcha resolution...")
        try:
            await self.page.wait_for_selector(selector, timeout=5_000, state="detached")
        except pw_timeout_error():
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
