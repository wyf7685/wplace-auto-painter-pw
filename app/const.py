import base64
import functools
import json
import sys
from pathlib import Path
from typing import ClassVar

IS_FROZEN = getattr(sys, "frozen", False)
APP_NAME = "wplace-auto-painter"

CWD = (Path(sys.executable).parent if IS_FROZEN else Path.cwd()).resolve()
DATA_DIR = CWD / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR = DATA_DIR / "templates"
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = DATA_DIR / "config.json"
CONFIG_SCHEMA_FILE = DATA_DIR / ".config.schema.json"

ASSETS_DIR = Path(__file__).parent.resolve() / "assets"


class _Assets:
    icon: ClassVar[Path] = ASSETS_DIR.joinpath("icon", "gui.ico")
    locales: ClassVar[Path] = ASSETS_DIR.joinpath("locales")

    @staticmethod
    @functools.cache
    def _read(*path: str) -> str:
        return ASSETS_DIR.joinpath(*path).read_text("utf-8")

    def page_init(self) -> str:
        return self._read("js", "page_init.js")

    def paint_btn(self, script_data: dict[str, str]) -> str:
        return self._read("js", "paint_btn.js").replace(
            "{{script_data}}", base64.b64encode(json.dumps(script_data).encode()).decode()
        )


assets = _Assets()
