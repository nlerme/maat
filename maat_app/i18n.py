from __future__ import annotations

import json
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
TRANSLATIONS_DIR = ROOT / "translations"

LANGUAGES = {
    "fr": {"flag": "🇫🇷", "label": "Français", "short": "FR"},
    "en": {"flag": "🇬🇧", "label": "English", "short": "EN"},
}


def _load_translations() -> dict[str, dict[str, str]]:
    result: dict[str, dict[str, str]] = {}
    for lang in LANGUAGES:
        path = TRANSLATIONS_DIR / f"{lang}.json"
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                result[lang] = json.load(handle)
        else:
            result[lang] = {}
    return result


TRANSLATIONS: dict[str, dict[str, str]] = _load_translations()


def normalize_language(value: Any) -> str:
    lang = str(value or "fr").lower()
    return "en" if lang.startswith("en") else "fr"


def translate(lang: str, key: str, **kwargs: Any) -> str:
    lang = normalize_language(lang)
    text = TRANSLATIONS.get(lang, TRANSLATIONS.get("fr", {})).get(key, TRANSLATIONS.get("fr", {}).get(key, key))
    try:
        return text.format(**kwargs)
    except Exception:
        return text
