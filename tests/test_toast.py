import builtins
import importlib.util
from collections.abc import Sequence
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


def _load_toast(platform: str, missing_dependency: str) -> tuple[ModuleType, list[str]]:
    imports: list[str] = []
    platform_module = ModuleType("sys")
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
        if name in {"winerror", "windows_toasts", "winrt.windows.ui.notifications"}:
            dependency = ModuleType(name)
            for attribute in fromlist or ():
                setattr(dependency, attribute, object())
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
