import builtins
import importlib.util
import sys
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


class _FakeToastDuration:
    Default = object()
    Short = object()
    Long = object()


class _FakeToast:
    def __init__(self, text_fields: Sequence[str] | None = None, *, duration: object = None) -> None:
        self.text_fields = list(text_fields or ())
        self.duration = duration
        self.images: list[object] = []

    def AddImage(self, image: object) -> None:  # noqa: N802
        self.images.append(image)


class _FakeToastDisplayImage:
    @staticmethod
    def fromPath(path: object, *, position: object) -> object:  # noqa: N802
        _ = path, position
        return object()


class _FakeToastImagePosition:
    AppLogo = object()


class _FakeNotificationSetting:
    ENABLED = object()
    DISABLED_BY_MANIFEST = object()


def _hresult_from_win32(code: int) -> int:
    if code <= 0:
        return code
    return ((code & 0xFFFF) | 0x80070000) - 0x100000000


class _FakeToastNotifier:
    def __init__(self, winerror_code: int) -> None:
        self._winerror_code = winerror_code

    @property
    def setting(self) -> object:
        raise OSError(22, "Element not found.", None, self._winerror_code)


def _toaster_cls_for_winerror(winerror_code: int) -> type:
    class _FakeInteractableWindowsToaster:
        def __init__(self, name: str = "", aumid: str = "") -> None:
            _ = name, aumid
            self.toastNotifier = _FakeToastNotifier(winerror_code)

    return _FakeInteractableWindowsToaster


def _load_toast(
    platform: str,
    missing_dependency: str | None,
    *,
    toaster_cls: type | None = None,
) -> tuple[ModuleType, list[str]]:
    imports: list[str] = []
    platform_module = ModuleType("sys")
    platform_module.__dict__.update(sys.__dict__)
    platform_module.__dict__["platform"] = platform

    def import_module(
        name: str,
        globals_: dict[str, Any] | None = None,
        locals_: dict[str, Any] | None = None,
        fromlist: Sequence[str] | None = (),
        level: int = 0,
    ) -> ModuleType:
        imports.append(name)
        if name == "sys":
            return platform_module
        if name in {"app.config", "winreg"}:
            raise AssertionError("Unavailable notifications must not access config or the registry")
        if name == missing_dependency:
            raise ImportError(f"Notification dependency unavailable: {name}")
        if name == "winerror":
            dependency = ModuleType(name)
            dependency.__dict__["ERROR_NOT_FOUND"] = 1168
            dependency.__dict__["HRESULT_FROM_WIN32"] = _hresult_from_win32
            return dependency
        if name == "windows_toasts":
            dependency = ModuleType(name)
            for attribute in fromlist or ():
                setattr(dependency, attribute, object())
            dependency.__dict__["Toast"] = _FakeToast
            dependency.__dict__["ToastDisplayImage"] = _FakeToastDisplayImage
            dependency.__dict__["ToastDuration"] = _FakeToastDuration
            dependency.__dict__["ToastImagePosition"] = _FakeToastImagePosition
            if toaster_cls is not None:
                dependency.__dict__["InteractableWindowsToaster"] = toaster_cls
            return dependency
        if name == "winrt.windows.ui.notifications":
            dependency = ModuleType(name)
            dependency.__dict__["NotificationSetting"] = _FakeNotificationSetting
            return dependency
        return builtins.__import__(name, globals_, locals_, fromlist or (), level)

    path = Path(__file__).resolve().parents[1] / "app" / "utils" / "toast.py"
    spec = importlib.util.spec_from_file_location("toast_under_test", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    module.__dict__["__builtins__"] = vars(builtins) | {"__import__": import_module}
    spec.loader.exec_module(module)
    return module, imports


@pytest.mark.parametrize("missing_dependency", ["winerror", "windows_toasts", "winrt.windows.ui.notifications"])
def test_windows_notification_import_failure_is_a_noop(missing_dependency: str) -> None:
    toast, imports = _load_toast("win32", missing_dependency)

    assert toast.notify("Title", "Body", duration=toast.Duration.Long) is None
    assert toast.notify_with_button("Title", "Body", button="Continue", duration=toast.Duration.Short) is False
    assert "app.config" not in imports
    assert "winreg" not in imports


def test_non_windows_notifications_do_not_load_windows_dependencies() -> None:
    toast, imports = _load_toast("linux", "windows_toasts")

    assert toast.notify("Title", "Body", duration=toast.Duration.Long) is None
    assert toast.notify_with_button("Title", "Body", button="Continue", duration=toast.Duration.Short) is False
    assert not {"winerror", "windows_toasts", "winrt.windows.ui.notifications", "app.config", "winreg"}.intersection(
        imports
    )


def test_windows_toast_does_not_repeat_registered_app_identity() -> None:
    toast, _ = _load_toast("win32", None)

    app_toast = toast._build_toast(toast.APP_NAME_HUMAN_READABLE, "Resolve the verification challenge")
    custom_toast = toast._build_toast("Verification required", "Resolve the verification challenge")

    assert app_toast.text_fields == ["Resolve the verification challenge"]
    assert app_toast.images == []
    assert custom_toast.text_fields == ["Verification required", "Resolve the verification challenge"]


@pytest.mark.skipif(sys.platform != "win32", reason="OSError.winerror is Windows-only")
@pytest.mark.parametrize(
    "winerror_code",
    [
        1168,  # winerror.ERROR_NOT_FOUND
        -2147023728,  # HRESULT_FROM_WIN32(ERROR_NOT_FOUND) == 0x80070490
    ],
)
def test_missing_notification_setting_is_treated_as_enabled(winerror_code: int) -> None:
    toast, _ = _load_toast("win32", None, toaster_cls=_toaster_cls_for_winerror(winerror_code))

    assert toast._get_notification_setting() is _FakeNotificationSetting.ENABLED


@pytest.mark.skipif(sys.platform != "win32", reason="OSError.winerror is Windows-only")
def test_other_notification_setting_oserror_disables_toasts() -> None:
    toast, _ = _load_toast("win32", None, toaster_cls=_toaster_cls_for_winerror(12345))

    assert toast._get_notification_setting() is _FakeNotificationSetting.DISABLED_BY_MANIFEST
