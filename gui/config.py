import json
import sys
from pathlib import Path
from typing import Any

from app.config import CONFIG_FILE, CONFIG_SCHEMA_FILE, DATA_DIR, TEMPLATES_DIR, export_config_schema
from app.log import logger

GUI_ICO = (
    Path(sys._MEIPASS)  # noqa: SLF001  # pyright: ignore[reportAttributeAccessIssue]
    if getattr(sys, "frozen", False)
    else Path(__file__).parent
) / "gui.ico"
schema_path = "../" + CONFIG_SCHEMA_FILE.resolve().relative_to(Path.cwd().resolve()).as_posix()


def ensure_data_dirs() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning(f"Error ensuring data directories: {e}")


def read_config() -> dict[str, Any]:
    try:
        if not CONFIG_FILE.is_file():
            return {}
        with Path.open(CONFIG_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_config(cfg: dict[str, Any]) -> bool:
    export_config_schema()
    cfg = {"$schema": schema_path} | cfg
    try:
        ensure_data_dirs()
        with Path.open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        return False
    else:
        return True
