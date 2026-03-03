from dataclasses import dataclass

from app.const import DATA_DIR

# How long (seconds) playwright may sit completely idle before being shut down.
PLAYWRIGHT_IDLE_TIMEOUT: int = 60 * 10  # 10 minutes

# Local directory used as PLAYWRIGHT_BROWSERS_PATH.
PLAYWRIGHT_BROWSERS_PATH = DATA_DIR / "playwright-browsers"


@dataclass(frozen=True)
class MirrorSource:
    name: str
    url: str
    # Lower priority value = tried first when latency is equal.
    priority: int


# Mirrors listed in ascending priority order (smaller priority = preferred).
MIRRORS: list[MirrorSource] = [
    MirrorSource("Default", "https://playwright.azureedge.net", 1),
    MirrorSource("Taobao", "https://registry.npmmirror.com/-/binary/playwright", 2),
]
