"""Windows toast notification helpers.

On non-Windows platforms every public function is a no-op so callers need
not guard against the platform themselves.  The only requirement is that
``win11toast`` is installed, which ``pyproject.toml`` enforces via the
``sys_platform == 'win32'`` marker.
"""

import contextlib
import sys
from typing import Any, TypeGuard

from app.assets import ICON_PATH
from app.log import logger

# Available only on Windows; import is guarded by the platform check below.
_w11t = None

if sys.platform == "win32":
    with contextlib.suppress(ImportError):
        import win11toast as _w11t


def _available[M](mod: M | None) -> TypeGuard[M]:
    return mod is not None


def is_available() -> bool:
    """Return ``True`` when win11toast is importable on this platform."""
    return _available(_w11t)


_ICON = str(ICON_PATH) if ICON_PATH.is_file() else None


def notify(
    title: str,
    body: str = "",
    # Passed through to win11toast.notify(); ignored on unsupported platforms.
    **kwargs: Any,
) -> None:
    """Fire-and-forget toast notification.

    Silently does nothing when not running on Windows or when win11toast is
    unavailable.
    """
    if not _available(_w11t):
        return

    with contextlib.suppress(Exception):
        _w11t.notify(title, body, icon=_ICON, **kwargs)


def notify_with_button(
    title: str,
    body: str = "",
    *,
    button: str = "OK",
    **kwargs: Any,
) -> bool:
    """Show a toast with a single action button and block until dismissed.

    Uses ``win11toast.toast()`` which is the synchronous-blocking variant;
    it runs its own ``asyncio.run()`` internally and returns only after the
    user dismisses the notification or clicks a button.

    Returns ``True`` when the user clicked the button, ``False`` when the
    notification timed out or was dismissed, or when an error occurred.
    Always returns ``False`` on non-Windows / unavailable platforms.
    """
    if not _available(_w11t):
        return False

    try:
        # toast() is the blocking counterpart of notify(); it awaits the
        # activated/dismissed/failed event before returning.
        result = _w11t.toast(
            title,
            body,
            buttons=[button],
            icon=_ICON,
            **kwargs,
        )
    except Exception:
        logger.opt(exception=True).warning("Failed to show toast notification")
        return False
    else:
        # On button click: {'arguments': 'http:<button>', 'user_input': {}}
        # On timeout/dismiss: [] (the initial value of the module-level list)
        return isinstance(result, dict) and result.get("arguments") == f"http:{button}"
