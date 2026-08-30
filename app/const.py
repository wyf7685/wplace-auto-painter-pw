import base64
import json
import sys
from pathlib import Path
from typing import ClassVar, NoReturn

IS_FROZEN = getattr(sys, "frozen", False)
APP_NAME = "wplace-auto-painter"
REPOSITORY_OWNER = "wyf7685"
REPOSITORY_NAME = "wplace-auto-painter-pw"
REPOSITORY_URL = f"https://github.com/{REPOSITORY_OWNER}/{REPOSITORY_NAME}"
REPOSITORY_ACTIONS_URL = f"{REPOSITORY_URL}/actions"


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
    icon: ClassVar[Path] = ASSETS_DIR / "icon" / "gui.ico"
    locales: ClassVar[Path] = ASSETS_DIR / "locales"
    # Keyed by path, holding (mtime_ns, content) so edits are picked up without a restart.
    _cache: ClassVar[dict[tuple[str, ...], tuple[int, str]]] = {}

    def __init__(self) -> NoReturn:
        raise NotImplementedError

    @classmethod
    def _read(cls, *path: str) -> str:
        fp = ASSETS_DIR.joinpath(*path)
        if not fp.exists():
            raise FileNotFoundError(f"Asset not found: {fp}")

        mtime = fp.stat().st_mtime_ns
        if (cached := cls._cache.get(path)) is not None and cached[0] == mtime:
            return cached[1]

        content = fp.read_text("utf-8")
        cls._cache[path] = (mtime, content)
        return content

    def page_init(self) -> str:
        return self._read("js", "page_init.js")

    def paint_btn(self, script_data: list[object]) -> str:
        return self._read("js", "paint_btn.js").replace(
            "{{script_data}}", base64.b64encode(json.dumps(script_data).encode()).decode()
        )


assets = object.__new__(Assets)
