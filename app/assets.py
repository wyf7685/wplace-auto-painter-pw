import base64
import json

from .config import ASSETS_DIR


class Assets:
    @staticmethod
    def _read(name: str) -> str:
        return ASSETS_DIR.joinpath(name).read_text("utf-8")

    def page_init(self, color_id: int = 1, show_all_colors: bool = False) -> str:
        return (
            self._read("page_init.js")
            .replace("{{color_id}}", str(color_id))
            .replace("{{show_all_colors}}", "true" if show_all_colors else "false")
        )

    def paint_btn(self, script_data: dict[str, str]) -> str:
        return self._read("paint_btn.js").replace(
            "{{script_data}}", base64.b64encode(json.dumps(script_data).encode()).decode()
        )


assets = Assets()
