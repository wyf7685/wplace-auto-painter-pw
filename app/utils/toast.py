"""Windows toast notification helpers backed by windows_toasts.

Public helpers are no-ops when windows_toasts is unavailable, including on
non-Windows platforms. Both notification types use the application's registered
AUMID so Windows can associate them with the configured display name and icon.
``InteractableWindowsToaster`` is used for both fire-and-forget notifications
and notifications with action buttons because activation callbacks require a
recognised AUMID.
"""

import contextlib
import enum
import functools
import sys
import threading
from typing import TYPE_CHECKING, TypeGuard

from app.const import APP_ID, APP_NAME_HUMAN_READABLE, assets
from app.log import logger

if TYPE_CHECKING:
    from windows_toasts import Toast, ToastActivatedEventArgs, ToastDisplayImage
    from windows_toasts import ToastDuration as Duration
    from winrt.windows.ui.notifications import NotificationSetting
else:

    class Duration(enum.Enum):
        """
        Possible values for duration to display toast for
        """

        Default = "Default"
        Short = "short"
        Long = "long"

    class NotificationSetting(enum.IntEnum):
        ENABLED = 0
        DISABLED_FOR_APPLICATION = 1
        DISABLED_FOR_USER = 2
        DISABLED_BY_GROUP_POLICY = 3
        DISABLED_BY_MANIFEST = 4


ERROR_NOT_FOUND = 1168  # winerror.ERROR_NOT_FOUND

# windows_toasts is a Windows-only optional dependency; import is guarded below.
_wt = None

if sys.platform == "win32":

    def _load_windows_toasts() -> None:
        global _wt, Duration, NotificationSetting

        try:
            import windows_toasts as wt
            from winrt.windows.ui.notifications import NotificationSetting as Setting
        except ImportError:
            logger.debug("windows_toasts is not available; toast notifications will be disabled")
            return

        logger.debug("windows_toasts is available")
        _wt = wt
        Duration = wt.ToastDuration
        NotificationSetting = Setting

    _load_windows_toasts()
    del _load_windows_toasts


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


@functools.cache
def _warn_failed_get_setting() -> None:
    logger.warning(f"Failed to get notification setting: {sys.exception()!r}")


def _get_notification_setting() -> NotificationSetting:
    if not _available(_wt):
        return NotificationSetting.DISABLED_BY_MANIFEST

    try:
        toaster = _wt.InteractableWindowsToaster(APP_NAME_HUMAN_READABLE, APP_ID)
        setting = toaster.toastNotifier.setting
    except OSError as e:
        # The notification settings key may not exist before the first toast is shown.
        # Treat ERROR_NOT_FOUND as enabled so Windows can create the key on first delivery.
        if e.winerror == ERROR_NOT_FOUND:
            setting = NotificationSetting.ENABLED
        else:
            _warn_failed_get_setting()
            setting = NotificationSetting.DISABLED_BY_MANIFEST

    except Exception:
        _warn_failed_get_setting()
        setting = NotificationSetting.DISABLED_BY_MANIFEST

    return setting


@functools.cache
def _ensure_aumid() -> None:
    import winreg

    key_path = f"SOFTWARE\\Classes\\AppUserModelId\\{APP_ID}"
    with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, key_path) as master_key:
        winreg.SetValueEx(master_key, "DisplayName", 0, winreg.REG_SZ, APP_NAME_HUMAN_READABLE)
        winreg.SetValueEx(master_key, "IconUri", 0, winreg.REG_SZ, str(assets.icon))


def _is_disabled() -> bool:
    """Return ``True`` if notifications are disabled."""
    from app.config import Config

    try:
        _ensure_aumid()
    except Exception:
        logger.opt(exception=True).warning("Failed to register AUMID for toast notifications")
        return True

    return Config.load().disable_notifications or _get_notification_setting() != NotificationSetting.ENABLED


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
    if not _available(_wt) or _is_disabled():
        return

    try:
        _wt.InteractableWindowsToaster(APP_NAME_HUMAN_READABLE, APP_ID).show_toast(_build_toast(title, body, duration))
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
    if not _available(_wt) or _is_disabled():
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
        _wt.InteractableWindowsToaster(APP_NAME_HUMAN_READABLE, APP_ID).show_toast(toast)
        done.wait()  # block until on_activated or on_dismissed fires
    except Exception:
        logger.opt(exception=True).warning("Failed to show toast notification")
        return False

    return clicked
