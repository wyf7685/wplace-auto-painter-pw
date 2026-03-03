from pathlib import Path

APP_NAME = "wplace-auto-painter"
DATA_DIR = Path.cwd().resolve().joinpath("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR = DATA_DIR / "templates"
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
CONFIG_FILE = DATA_DIR / "config.json"
CONFIG_SCHEMA_FILE = DATA_DIR / ".config.schema.json"
