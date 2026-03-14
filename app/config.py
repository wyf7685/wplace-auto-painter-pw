import json
from typing import ClassVar, Literal

from pydantic import BaseModel, Field, model_validator

from app.const import CONFIG_FILE, CONFIG_SCHEMA_FILE
from app.schemas import UserConfig


class Config(BaseModel):
    _cache: ClassVar[Config | None] = None
    # Runtime-only flag; never written to config.json.
    # Set to True by the tray entry point so other modules can adapt their
    # behaviour (e.g. wait for user confirmation before opening a browser).
    _background_mode: ClassVar[bool] = False

    @classmethod
    def set_background_mode(cls, value: bool = True) -> None:
        cls._background_mode = value

    @classmethod
    def is_background_mode(cls) -> bool:
        return cls._background_mode

    users: list[UserConfig] = Field(description="List of user configurations")
    browser: Literal["chromium", "firefox", "webkit", "chrome", "msedge"] = Field(
        description="Playwright browser type to use"
    )
    proxy: str | None = Field(default=None, description="Optional proxy server URL to access wplace")
    log_level: Literal["TRACE", "DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = Field(
        default="DEBUG", description="Logging level for console"
    )
    check_update: bool = Field(default=True, description="Whether to check for updates")
    tray_mode: bool = Field(
        default=False,
        description="Hide the console and show a system tray icon instead (Windows only)",
    )
    disable_notifications: bool = Field(
        default=False,
        description="Whether to disable desktop notifications (not recommended)",
    )

    @model_validator(mode="after")
    def validate_users(self) -> Config:
        if not self.users:
            raise ValueError("users cannot be empty")

        seen: set[str] = set()
        duplicates: set[str] = set()
        for user in self.users:
            identifier = user.identifier
            if identifier in seen:
                duplicates.add(identifier)
            seen.add(identifier)

        if duplicates:
            dup_text = ", ".join(sorted(duplicates))
            raise ValueError(f"duplicate user identifier(s): {dup_text}")

        return self

    @classmethod
    def load(cls) -> Config:
        if cls._cache is None:
            cls._cache = cls.model_validate_json(CONFIG_FILE.read_text("utf-8"), extra="ignore")
        return cls._cache

    def save(self) -> None:
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


def export_config_schema() -> None:
    CONFIG_SCHEMA_FILE.write_text(json.dumps(Config.model_json_schema()), encoding="utf-8")
