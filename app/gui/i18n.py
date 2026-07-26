import json
from collections.abc import Mapping
from typing import ClassVar, Final, Literal, get_args

from app.const import assets

type LanguageCode = Literal["zh_CN", "en_US"]
type Translations = Mapping[str, str]

_DEFAULT_LANGUAGE: Final[LanguageCode] = "zh_CN"
_SUPPORTED_LANGUAGES: Final[tuple[LanguageCode, ...]] = get_args(LanguageCode.__value__)


def _load_language(language: LanguageCode) -> Translations:
    locale_file = assets.locales / f"{language}.json"
    if not locale_file.is_file():
        return {}

    try:
        loaded = json.loads(locale_file.read_text(encoding="utf-8"))
    except Exception:
        return {}

    if not isinstance(loaded, dict):
        return {}

    return {key: value for key, value in loaded.items() if isinstance(key, str) and isinstance(value, str)}


class Lang:
    _translations: ClassVar[dict[LanguageCode, Translations]] = {}
    _current_language: LanguageCode = _DEFAULT_LANGUAGE

    def __init__(self) -> None:
        raise NotImplementedError

    @classmethod
    def _ensure_loaded(cls, language: LanguageCode) -> None:
        if language not in cls._translations:
            cls._translations[language] = _load_language(language)

    @classmethod
    def _get_translations(cls, language: LanguageCode) -> Translations:
        cls._ensure_loaded(language)
        return cls._translations.get(language, {})

    def _ensure_key(self, key: str) -> str:
        return (
            self._get_translations(self._current_language).get(key)
            or self._get_translations(_DEFAULT_LANGUAGE).get(key)
            or key
        )

    @property
    def supported_languages(self) -> tuple[LanguageCode, ...]:
        return _SUPPORTED_LANGUAGES

    def get_language(self) -> LanguageCode:
        return self._current_language

    def set_language(self, language: str | None) -> LanguageCode:
        target = language if language in self.supported_languages else _DEFAULT_LANGUAGE
        self._ensure_loaded(target)
        self._current_language = target
        return self._current_language

    def translate(self, key: str, **kwargs: object) -> str:
        text = self._ensure_key(key)
        if not kwargs:
            return text

        try:
            return text.format(**kwargs)
        except Exception:
            return text


lang = object.__new__(Lang)
tr = lang.translate
