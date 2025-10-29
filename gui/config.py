import json
import os
from typing import Any


# data 目录位于仓库根的 data
DATA_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "data"))
CONFIG_PATH = os.path.join(DATA_DIR, "config.json")
TEMPLATES_DIR = os.path.join(DATA_DIR, "templates")
GUI_ICO = os.path.join(DATA_DIR, "gui.ico")


def ensure_data_dirs() -> None:
    try:
        os.makedirs(DATA_DIR, exist_ok=True)
        os.makedirs(TEMPLATES_DIR, exist_ok=True)
    except Exception:
        # 忽略创建目录时的异常，调用方会在需要时处理写入错误
        pass


def read_config() -> dict[str, Any]:
    try:
        if not os.path.isfile(CONFIG_PATH):
            return {}
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def write_config(cfg: dict[str, Any]) -> bool:
    try:
        ensure_data_dirs()
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, ensure_ascii=False, indent=2)
        return True
    except Exception:
        return False
