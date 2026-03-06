"""Windows toast notification helpers using windows_toasts.

On non-Windows platforms every public function is a no-op so callers need
not guard against the platform themselves.

All three toasters share the same ``APP_NAME`` as the notification sender.
``WindowsToaster`` is used for fire-and-forget notifications (no buttons /
callbacks).  ``InteractableWindowsToaster`` is used whenever a callback or
an action button is involved — it requires a recognised AUMID, defaulting
to cmd.exe, which is enough for our purposes.
"""

import contextlib
import sys
import threading
from collections.abc import Callable
from enum import Enum
from typing import TYPE_CHECKING, TypeGuard

from app.const import APP_NAME, assets
from app.log import logger

if TYPE_CHECKING:
    from windows_toasts import Toast, ToastActivatedEventArgs, ToastDisplayImage
    from windows_toasts import ToastDuration as Duration
else:

    class Duration(Enum):
        """
        Possible values for duration to display toast for
        """

        Default = "Default"
        Short = "short"
        Long = "long"


# windows_toasts is a Windows-only optional dependency; import is guarded below.
_wt = None

if sys.platform == "win32":
    with contextlib.suppress(ImportError):
        import windows_toasts as _wt
        from windows_toasts import ToastDuration as Duration


def _available[M](mod: M | None) -> TypeGuard[M]:
    """Type guard for windows_toasts availability."""
    return mod is not None


def is_available() -> bool:
    """Return ``True`` when windows_toasts is importable on this platform."""
    return _available(_wt)


# ── Internal helpers ───────────────────────────────────────────────────────────


def _logo_image() -> ToastDisplayImage | None:
    """Return a ``ToastDisplayImage`` for the app icon, or ``None`` if unavailable."""
    if not _available(_wt) or not assets.icon.is_file():
        return None
    with contextlib.suppress(Exception):
        return _wt.ToastDisplayImage.fromPath(
            assets.icon,
            position=_wt.ToastImagePosition.AppLogo,
        )
    return None


def _build_toast(title: str, body: str, duration: Duration = Duration.Default) -> Toast:
    """Construct a ``Toast`` with text, optional app logo, and duration."""
    assert _available(_wt)
    toast = _wt.Toast([title, body], duration=duration)
    logo = _logo_image()
    if logo is not None:
        toast.AddImage(logo)
    return toast


# ── Public API ─────────────────────────────────────────────────────────────────


def notify(
    title: str,
    body: str = "",
    *,
    duration: Duration = Duration.Default,
) -> None:
    """Fire-and-forget toast notification.

    Non-blocking; returns immediately.  Does nothing on non-Windows or when
    windows_toasts is unavailable.
    """
    if not _available(_wt):
        return

    try:
        _wt.WindowsToaster(APP_NAME).show_toast(_build_toast(title, body, duration))
    except Exception:
        logger.opt(exception=True).warning("Failed to show toast notification")


async def toast_async(
    title: str,
    body: str = "",
    *,
    duration: Duration = Duration.Default,
    on_click: Callable[[], None] | None = None,
) -> None:
    """Async fire-and-forget toast with an optional click callback.

    Always non-blocking; the underlying ``show_toast`` call is synchronous
    but near-instant.  The optional *on_click* callback is invoked on a
    Windows thread when the user clicks the notification body.

    Uses ``InteractableWindowsToaster`` when *on_click* is provided
    (required for reliable ``on_activated`` delivery); falls back to
    ``WindowsToaster`` otherwise.
    """
    if not _available(_wt):
        return

    try:
        toast = _build_toast(title, body, duration)
        if on_click is not None:
            toast.on_activated = lambda _args: on_click()
            toaster = _wt.InteractableWindowsToaster(APP_NAME)
        else:
            toaster = _wt.WindowsToaster(APP_NAME)
        toaster.show_toast(toast)
    except Exception:
        logger.opt(exception=True).warning("Failed to show toast notification")


def notify_with_button(
    title: str,
    body: str = "",
    *,
    button: str = "OK",
    duration: Duration = Duration.Default,
) -> bool:
    """Show a toast with a single action button and block until dismissed.

    Uses a ``threading.Event`` to block the calling thread until the
    Windows notification is either clicked or dismissed/timed-out.

    Returns ``True`` when the user clicked the button, ``False`` on
    timeout / dismiss / error or on non-Windows / unavailable platforms.
    """
    if not _available(_wt):
        return False

    done = threading.Event()
    clicked = False

    def _on_activated(args: ToastActivatedEventArgs) -> None:
        nonlocal clicked
        clicked = args.arguments == button
        done.set()

    def _on_dismissed(_: object) -> None:  # ToastDismissedEventArgs from winrt
        done.set()

    try:
        toast = _build_toast(title, body, duration)
        toast.on_activated = _on_activated
        toast.on_dismissed = _on_dismissed
        toast.AddAction(_wt.ToastButton(content=button, arguments=button))
        _wt.InteractableWindowsToaster(APP_NAME).show_toast(toast)
        done.wait()  # block until on_activated or on_dismissed fires
    except Exception:
        logger.opt(exception=True).warning("Failed to show toast notification")
        return False

    return clicked
