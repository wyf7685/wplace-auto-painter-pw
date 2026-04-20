import base64
import functools
import json
import sys
from pathlib import Path
from typing import ClassVar, NoReturn

IS_FROZEN = getattr(sys, "frozen", False)
APP_NAME = "wplace-auto-painter"

CWD = (Path(sys.executable).parent if IS_FROZEN else Path.cwd()).resolve()
DATA_DIR = CWD / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR = DATA_DIR / "templates"
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
USER_CONTEXT_DIR = DATA_DIR / "user_context"
CONFIG_FILE = DATA_DIR / "config.json"
CONFIG_SCHEMA_FILE = DATA_DIR / ".config.schema.json"

ASSETS_DIR = Path(__file__).parent.resolve() / "assets"


class Assets:
    icon: ClassVar[Path] = ASSETS_DIR.joinpath("icon", "gui.ico")
    locales: ClassVar[Path] = ASSETS_DIR.joinpath("locales")

    def __init__(self) -> NoReturn:
        raise NotImplementedError

    @staticmethod
    @functools.cache
    def _read(*path: str, __cache: dict[int, tuple[int, str]] = {}) -> str:  # noqa: B006
        fp = ASSETS_DIR.joinpath(*path)
        if not fp.exists():
            raise FileNotFoundError(f"Asset not found: {fp}")

        key = hash(path)
        mtime = fp.stat().st_mtime_ns
        if (cache := __cache.get(key)) is not None and cache[0] == mtime:
            return cache[1]
        __cache[key] = (mtime, fp.read_text("utf-8"))
        return __cache[key][1]

    def page_init(self) -> str:
        return self._read("js", "page_init.js")

    def paint_btn(self, script_data: list[str]) -> str:
        return self._read("js", "paint_btn.js").replace(
            "{{script_data}}", base64.b64encode(json.dumps(script_data).encode()).decode()
        )


assets = object.__new__(Assets)
