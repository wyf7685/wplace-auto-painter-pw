import base64
import functools
import json
import sys
from pathlib import Path
from typing import Any

ASSETS_DIR = (
    Path(sys._MEIPASS)  # noqa: SLF001  # pyright: ignore[reportAttributeAccessIssue]
    if getattr(sys, "frozen", False)
    else Path(__file__).parent
) / "assets"


class Assets:
    @staticmethod
    @functools.cache
    def _read(name: str) -> str:
        return ASSETS_DIR.joinpath(name).read_text("utf-8")

    def page_init(self) -> str:
        return self._read("page_init.js")

    def paint_map(self, script_data: dict[str, Any]) -> str:
        return self._read("paint_map.js").replace(
            "{{script_data}}", base64.b64encode(json.dumps(script_data).encode()).decode()
        )


assets = Assets()
