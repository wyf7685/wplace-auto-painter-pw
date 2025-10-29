import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)
ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
GUI_DIR = ROOT_DIR / "gui"
CONFIG_PATH = DATA_DIR / "config.json"
TEMPLATES_DIR = DATA_DIR / "templates"
GUI_ICO = GUI_DIR / "gui.ico"


def ensure_data_dirs() -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.info(f"Error ensuring data directories: {e}")


def read_config() -> dict[str, Any]:
    try:
        if not CONFIG_PATH.is_file():
            return {}
        with Path.open(CONFIG_PATH, "r",encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}
def write_config(cfg: dict[str, Any]) -> bool:
    try:
        ensure_data_dirs()
        with Path.open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
    except Exception:
        return False
    else:
        return True
