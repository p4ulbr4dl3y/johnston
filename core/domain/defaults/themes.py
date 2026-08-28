"""Modern built-in themes and color palettes for Johnston."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from core.domain.entities.theme import Theme

if TYPE_CHECKING:
    THEMES: dict[str, Theme]
    BUILTIN_THEMES: list[Theme]
    ZINC_DARK: Theme
    NATIVE: Theme

THEMES_JSON_PATH = Path(__file__).with_name("themes.json")

_themes_cache: dict[str, Theme] | None = None

_NAME_ALIASES: dict[str, str] = {
    "ZINC_DARK": "zinc",
    "EVERFOREST_DARK": "everforest",
    "NATIVE": "native",
    "NATIVE_DARK": "native",
}


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


def load_builtin_themes() -> list[Theme]:
    """Load and return all built-in themes."""
    return list_themes()


def __getattr__(name: str) -> Any:
    """Dynamically resolve theme constants, lists, and dicts."""
    if name == "THEMES":
        return _ensure_loaded()
    if name == "BUILTIN_THEMES":
        return list_themes()
    if name in _NAME_ALIASES:
        return _ensure_loaded()[_NAME_ALIASES[name]]

    normalized = name.lower().replace("_", "-")
    themes = _ensure_loaded()
    if normalized in themes:
        return themes[normalized]

    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def __dir__() -> list[str]:
    """List public symbols including theme names."""
    return list(globals().keys()) + [
        "THEMES",
        "BUILTIN_THEMES",
        *_NAME_ALIASES.keys(),
        *(t.replace("-", "_").upper() for t in _ensure_loaded()),
    ]


__all__ = [
    "THEMES",
    "BUILTIN_THEMES",
    "get_theme",
    "list_themes",
    "load_builtin_themes",
    "ZINC_DARK",
]
