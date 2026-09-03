from typing import Literal, assert_never

from app.exception import FetchFailed, TokenExpired
from app.log import logger
from app.schemas import PurchaseChargeConfig, PurchaseMaxChargeConfig, WplaceUserInfo
from app.wplace.page import UserContext

WPLACE_APP_URL = "https://wplace.live/"
WPLACE_PURCHASE_API_URL = "https://backend.wplace.live/purchase"
_PRODUCT_IDS = {"max_charges": 70, "charges": 80}
_PURCHASE_SCRIPT = """
async ({url, product}) => {
  const response = await fetch(url, {
    method: "POST",
    credentials: "include",
    body: JSON.stringify({product}),
    signal: AbortSignal.timeout(20_000),
  });
  return {
    status: response.status,
    body: await response.text(),
    cfMitigated: response.headers.get("cf-mitigated"),
  };
}
"""


async def _post_purchase(
    context: UserContext,
    purchase_type: Literal["max_charges", "charges"],
    amount: int,
) -> None:
    payload = {
        "url": WPLACE_PURCHASE_API_URL,
        "product": {"id": _PRODUCT_IDS[purchase_type], "amount": amount},
    }
    try:
        async with context.new_background_page() as (_, page):
            await page.goto(WPLACE_APP_URL, timeout=60_000, wait_until="domcontentloaded")
            result = await page.evaluate(_PURCHASE_SCRIPT, payload)
    except Exception as e:
        raise FetchFailed(f"Purchase request failed: {e!r}") from e

    if not isinstance(result, dict):
        raise FetchFailed(f"Purchase returned an invalid response: {result!r}")

    status = result.get("status")
    body = result.get("body")
    cf_mitigated = result.get("cfMitigated")
    if not isinstance(status, int) or not isinstance(body, str):
        raise FetchFailed(f"Purchase returned an invalid response: {result!r}")

    if status == 200:
        return
    if status == 401:
        raise TokenExpired("Authentication token expired during purchase")
    if isinstance(cf_mitigated, str) and cf_mitigated.lower() == "challenge":
        raise FetchFailed("Purchase request was challenged by Cloudflare")

    detail = body.strip()
    suffix = f": {detail[:500]}" if detail else ""
    raise FetchFailed(f"Purchase failed with HTTP {status}{suffix}")


async def process_purchase(context: UserContext, user_info: WplaceUserInfo) -> bool:
    cfg = context.user
    if cfg.auto_purchase is None:
        return False

    match cfg.auto_purchase:
        case PurchaseMaxChargeConfig(target_max=target, retain_droplets=retain):
            if target is not None and user_info.charges.max >= target:
                return False

            max_amount = (user_info.droplets - retain) // 500
            amount = min((target - user_info.charges.max) // 5, max_amount) if target is not None else max_amount
            if amount <= 0:
                return False

            logger.opt(colors=True).info(
                "Auto-purchasing max charges: "
                f"current_max=<y>{user_info.charges.max}</>, target_max=<y>{target}</>, amount=<y>{amount}</>"
            )
            await _post_purchase(context, "max_charges", amount)
            return True

        case PurchaseChargeConfig(retain_droplets=retain):
            amount = (user_info.droplets - retain) // 500
            if amount <= 0:
                return False

            logger.opt(colors=True).info(
                f"Auto-purchasing charges: current=<y>{user_info.charges.count:.2f}</>, amount=<y>{amount}</>"
            )
            await _post_purchase(context, "charges", amount)
            return True

        case x:
            assert_never(x)
