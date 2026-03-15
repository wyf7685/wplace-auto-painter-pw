from __future__ import annotations

import json
from pathlib import Path
from typing import Final, Literal

LanguageCode = Literal["zh_CN", "en_US"]

_DEFAULT_LANGUAGE: Final[LanguageCode] = "zh_CN"
_SUPPORTED_LANGUAGES: Final[tuple[LanguageCode, ...]] = ("zh_CN", "en_US")
_LOCALES_DIR: Final[Path] = Path(__file__).resolve().parent / "locales"

_translations: dict[LanguageCode, dict[str, str]] = {}
_current_language: LanguageCode = _DEFAULT_LANGUAGE


def _load_language(language: LanguageCode) -> dict[str, str]:
    locale_file = _LOCALES_DIR / f"{language}.json"
    if not locale_file.is_file():
        return {}

    try:
        loaded = json.loads(locale_file.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(loaded, dict):
        return {}

    return {
        key: value
        for key, value in loaded.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def _ensure_loaded(language: LanguageCode) -> None:
    if language not in _translations:
        _translations[language] = _load_language(language)


def set_language(language: str | None) -> LanguageCode:
    global _current_language

    target: LanguageCode = _DEFAULT_LANGUAGE
    if language in _SUPPORTED_LANGUAGES:
        target = language

    _ensure_loaded(target)
    _ensure_loaded("en_US")
    _current_language = target
    return _current_language


def get_language() -> LanguageCode:
    return _current_language


def supported_languages() -> tuple[LanguageCode, ...]:
    return _SUPPORTED_LANGUAGES


def tr(key: str, **kwargs: object) -> str:
    _ensure_loaded(_current_language)
    _ensure_loaded("en_US")

    text = _translations.get(_current_language, {}).get(key)
    if text is None:
        text = _translations.get("en_US", {}).get(key, key)

    if not kwargs:
        return text

    try:
        return text.format(**kwargs)
    except Exception:
        return text
