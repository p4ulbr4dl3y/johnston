"""Modern built-in themes and color palettes for Johnston."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from core.domain.entities.theme import Theme

THEMES_JSON_PATH = Path(__file__).with_name("themes.json")

_themes_cache: dict[str, Theme] | None = None


def _ensure_loaded() -> dict[str, Theme]:
    global _themes_cache
    if _themes_cache is None:
        with open(THEMES_JSON_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        _themes_cache = {item["name"]: Theme.from_dict(item) for item in data}
    return _themes_cache


def get_theme(name: str) -> Optional[Theme]:
    """Get a built-in theme by name."""
    return _ensure_loaded().get(name)


def list_themes() -> list[Theme]:
    """List all built-in themes."""
    return list(_ensure_loaded().values())


DEFAULT_THEME_NAME = "zinc"
ZINC_DARK: Theme = _ensure_loaded()["zinc"]

__all__ = [
    "DEFAULT_THEME_NAME",
    "ZINC_DARK",
    "get_theme",
    "list_themes",
]
