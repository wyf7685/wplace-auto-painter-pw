import contextlib
import json
from collections import Counter
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, model_validator

from app.const import CONFIG_FILE, CONFIG_SCHEMA_FILE
from app.exception import ConfigNotFound, ConfigParseFailed, NoUsersConfigured, UserTemplateInvalid
from app.schemas import UserConfig


class Config(BaseModel):
    _cache: ClassVar[Config | None] = None

    users: list[UserConfig] = Field(description="List of user configurations")
    browser: Literal["chromium", "firefox", "webkit", "chrome", "msedge"] = Field(
        description="Playwright browser type to use"
    )
    proxy: str | None = Field(default=None, description="Optional proxy server URL to access wplace")
    log_level: Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="DEBUG", description="Logging level for console"
    )
    check_update: bool = Field(default=True, description="Whether to check for updates")
    disable_notifications: bool = Field(
        default=False,
        description="Whether to disable desktop notifications (not recommended)",
    )
    language: Literal["zh_CN", "en_US"] = Field(
        default="zh_CN",
        description="GUI language code",
    )

    @model_validator(mode="after")
    def validate_users(self) -> Config:
        if not self.users:
            raise ValueError("users cannot be empty")

        duplicates = {id for id, cnt in Counter(u.identifier for u in self.users).items() if cnt > 1}
        if duplicates:
            raise ValueError(f"duplicate user identifier(s): {', '.join(sorted(duplicates))}")

        return self

    @classmethod
    def load(cls) -> Config:
        if cls._cache is None:
            cls._cache = cls.model_validate_json(CONFIG_FILE.read_text("utf-8"), extra="ignore")
        return cls._cache

    def save(self) -> None:
        from app.log import get_log_level
        from app.utils import SecretStrEncoder

        CONFIG_FILE.write_text(
            json.dumps(
                {"$schema": CONFIG_SCHEMA_FILE.relative_to(CONFIG_FILE.parent).as_posix()}
                | self.model_dump(exclude_defaults=True),
                indent=2,
                ensure_ascii=False,
                cls=SecretStrEncoder,
            ),
            encoding="utf-8",
        )
        Config._cache = self
        get_log_level.cache_clear()


def export_config_schema() -> None:
    with contextlib.suppress(Exception):
        CONFIG_SCHEMA_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_SCHEMA_FILE.write_text(json.dumps(Config.model_json_schema()), encoding="utf-8")


def ensure_config_ready() -> None:
    if not CONFIG_FILE.is_file():
        raise ConfigNotFound(f"Config file not found: {CONFIG_FILE}")

    try:
        cfg = Config.load()
    except Exception as exc:
        raise ConfigParseFailed("Failed to load config file") from exc

    if len(cfg.users) == 0:
        raise NoUsersConfigured("No users configured")

    for user in cfg.users:
        tp = user.template
        if not tp.file_id or not tp.file.is_file() or tp.file.stat().st_size == 0:
            raise UserTemplateInvalid(f"Template image is missing or invalid for user: {user.identifier}")
