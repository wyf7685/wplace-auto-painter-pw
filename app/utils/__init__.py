from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import toast as toast
    from .ansi_image import draw_ansi as draw_ansi
    from .color import parse_rgb_str as parse_rgb_str
    from .func import PerfLog as PerfLog
    from .func import SecretStrEncoder as SecretStrEncoder
    from .func import is_token_expired as is_token_expired
    from .func import logger_wrapper as logger_wrapper
    from .func import requests_proxies as requests_proxies
    from .func import run_sync as run_sync
    from .func import subprocess_options as subprocess_options
    from .func import with_retry as with_retry
    from .func import with_semaphore as with_semaphore
    from .highlight import Highlight as Highlight

_LOCATION = {
    "draw_ansi": "ansi_image",
    "parse_rgb_str": "color",
    "PerfLog": "func",
    "SecretStrEncoder": "func",
    "is_token_expired": "func",
    "logger_wrapper": "func",
    "requests_proxies": "func",
    "run_sync": "func",
    "subprocess_options": "func",
    "with_retry": "func",
    "with_semaphore": "func",
    "Highlight": "highlight",
}

__all__ = [*_LOCATION.keys(), "toast"]  # pyright: ignore[reportUnsupportedDunderAll]


def __load(name: str) -> object:
    import importlib

    if name == "toast":
        return importlib.import_module(".toast", package=__package__)
    if name in _LOCATION:
        module = importlib.import_module(f".{_LOCATION[name]}", package=__package__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __getattr__(name: str) -> object:
    value = __load(name)
    globals()[name] = value
    return value
