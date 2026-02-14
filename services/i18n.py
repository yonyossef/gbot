"""
Internationalization (i18n) for Shop Assistant bot.

Loads translations from locale/*.json. User language is stored per phone number.
"""

import json
from pathlib import Path
from typing import Dict, Optional

LOCALE_DIR = Path(__file__).resolve().parent.parent / "locale"
SUPPORTED_LANGS = ["en", "he"]
DEFAULT_LANG = "he"

# Loaded translations: {lang_code: {key: value}}
_translations: Dict[str, Dict[str, str]] = {}

# User language: phone -> lang_code
_user_lang: Dict[str, str] = {}


def _load_locale(lang: str) -> Dict[str, str]:
    """Load a locale file. Returns empty dict on error."""
    path = LOCALE_DIR / f"{lang}.json"
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, IOError):
        return {}


def _get_translations(lang: str) -> Dict[str, str]:
    """Get translations for a language, loading if needed."""
    if lang not in _translations:
        _translations[lang] = _load_locale(lang)
    return _translations[lang]


def t(key: str, lang: Optional[str] = None, **kwargs) -> str:
    """
    Get translated string for a key.

    Args:
        key: Translation key (e.g. "cancelled")
        lang: Language code. If None, uses DEFAULT_LANG (caller must pass lang for user-specific).
        **kwargs: Format placeholders (e.g. item_name="Milk" for {item_name})

    Returns:
        Translated string with placeholders replaced.
    """
    code = lang or DEFAULT_LANG
    if code not in SUPPORTED_LANGS:
        code = DEFAULT_LANG
    trans = _get_translations(code)
    text = trans.get(key, key)
    if kwargs:
        try:
            text = text.format(**kwargs)
        except KeyError:
            pass
    return text


def get_user_lang(phone: str) -> str:
    """Get language for a user (phone). Defaults to he."""
    return _user_lang.get(phone, DEFAULT_LANG)


def set_user_lang(phone: str, lang: str) -> None:
    """Set language for a user."""
    if lang in SUPPORTED_LANGS:
        _user_lang[phone] = lang


def reset_user_langs() -> None:
    """Clear all user language preferences (for tests)."""
    _user_lang.clear()


def get_supported_langs(display_lang: Optional[str] = None) -> list:
    """Return list of (code, display_name) for supported languages."""
    lang = display_lang or DEFAULT_LANG
    return [
        ("en", t("lang_name_en", lang)),
        ("he", t("lang_name_he", lang)),
    ]
