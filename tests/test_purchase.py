from __future__ import annotations

import asyncio
import contextlib
from typing import TYPE_CHECKING, Any, Literal, cast

import pytest

from app.exception import FetchFailed, TokenExpired
from app.wplace.purchase import WPLACE_APP_URL, WPLACE_PURCHASE_API_URL, _post_purchase

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

    from app.wplace.page import UserContext


class FakePage:
    def __init__(self, result: object) -> None:
        self.result = result
        self.goto_call: tuple[str, dict[str, object]] | None = None
        self.evaluate_call: tuple[str, object] | None = None

    async def goto(self, url: str, **kwargs: object) -> None:
        self.goto_call = (url, kwargs)

    async def evaluate(self, script: str, payload: object) -> object:
        self.evaluate_call = (script, payload)
        return self.result


class FakeUserContext:
    def __init__(self, page: FakePage) -> None:
        self.page = page

    @contextlib.asynccontextmanager
    async def new_background_page(self) -> AsyncGenerator[tuple[Any, FakePage]]:
        yield object(), self.page


def run_post_purchase(
    result: object,
    purchase_type: Literal["max_charges", "charges"] = "charges",
) -> FakePage:
    page = FakePage(result)
    context = cast("UserContext", FakeUserContext(page))
    asyncio.run(_post_purchase(context, purchase_type, 3))
    return page


@pytest.mark.parametrize(
    ("purchase_type", "product_id"),
    [("max_charges", 70), ("charges", 80)],
)
def test_post_purchase_uses_browser_fetch_contract(
    purchase_type: Literal["max_charges", "charges"],
    product_id: int,
) -> None:
    page = run_post_purchase({"status": 200, "body": "", "cfMitigated": None}, purchase_type)

    assert page.goto_call == (
        WPLACE_APP_URL,
        {"timeout": 60_000, "wait_until": "domcontentloaded"},
    )
    assert page.evaluate_call is not None
    script, payload = page.evaluate_call
    assert 'method: "POST"' in script
    assert 'credentials: "include"' in script
    assert "JSON.stringify({product})" in script
    assert "Content-Type" not in script
    assert payload == {
        "url": WPLACE_PURCHASE_API_URL,
        "product": {"id": product_id, "amount": 3},
    }


def test_post_purchase_stops_on_expired_token() -> None:
    with pytest.raises(TokenExpired, match="expired during purchase"):
        run_post_purchase({"status": 401, "body": "", "cfMitigated": None})


def test_post_purchase_reports_cloudflare_challenge() -> None:
    with pytest.raises(FetchFailed, match="challenged by Cloudflare"):
        run_post_purchase({"status": 403, "body": "challenge", "cfMitigated": "challenge"})
