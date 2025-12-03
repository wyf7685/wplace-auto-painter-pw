from typing import Literal, assert_never

import cloudscraper

from app.config import Config, UserConfig, WplaceCredentials
from app.exception import FetchFailed
from app.log import logger
from app.schemas import WplaceUserInfo
from app.utils import run_sync

WPLACE_PURCHASE_API_URL = "https://backend.wplace.live/purchase"
_SCRAPER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/140.0.0.0 Safari/537.36"
    ),
    "Sec-Ch-Ua": '"Chromium";v="140", "Not=A?Brand";v="24", "Google Chrome";v="140"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Origin": "https://wplace.live",
}


def _proxy_config() -> dict[str, str] | None:
    proxy = Config.load().proxy
    return {"http": proxy, "https": proxy} if proxy is not None else None


_proxies = _proxy_config()


@run_sync
def _post_purchase(credentials: WplaceCredentials, type: Literal["max_charges", "charges"], amount: int) -> None:  # noqa: A002
    try:
        resp = cloudscraper.create_scraper().post(
            WPLACE_PURCHASE_API_URL,
            headers=_SCRAPER_HEADERS,
            cookies=credentials.to_requests_cookies(),
            proxies=_proxies,
            json={"product": {"id": {"max_charges": 70, "charges": 80}[type], "amount": amount}},
            timeout=20,
        )
        resp.raise_for_status()
    except Exception as e:
        raise FetchFailed(f"Request failed: {e!r}") from e

    try:
        data = resp.json()
    except Exception as e:
        raise FetchFailed("Failed to parse JSON response") from e
    if not data["success"]:
        raise FetchFailed("Purchase failed: Unknown error")


async def do_purchase(cfg: UserConfig, user_info: WplaceUserInfo) -> bool:
    if cfg.auto_purchase is None:
        return False

    if cfg.auto_purchase.type == "max_charges":
        target = cfg.auto_purchase.target_max
        if target is not None and user_info.charges.max >= target:
            return False

        max_amount = (user_info.droplets - cfg.auto_purchase.retain_droplets) // 500
        amount = min((target - user_info.charges.max) // 5, max_amount) if target is not None else max_amount
        if amount <= 0:
            return False

        logger.opt(colors=True).info(
            "Auto-purchasing max charges: "
            f"current_max=<y>{user_info.charges.max}</>, target_max=<y>{target}</>, amount=<y>{amount}</>"
        )
        await _post_purchase(cfg.credentials, "max_charges", amount)
        return True

    if cfg.auto_purchase.type == "charges":
        amount = (user_info.droplets - cfg.auto_purchase.retain_droplets) // 500
        if amount <= 0:
            return False

        logger.opt(colors=True).info(
            f"Auto-purchasing charges: current=<y>{user_info.charges.count:.2f}</>, amount=<y>{amount}</>"
        )
        await _post_purchase(cfg.credentials, "charges", amount)
        return True

    assert_never(cfg.auto_purchase.type)
