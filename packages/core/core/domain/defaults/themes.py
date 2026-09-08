"""Modern built-in themes and color palettes for Johnston."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from core.domain.entities.theme import Theme

THEMES_JSON_PATH = Path(__file__).with_name("themes.json")

_themes_cache: dict[str, Theme] | None = None
_ZINC_DARK: Optional[Theme] = None


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

# Declared for typing/`__all__`; resolved lazily on first access via ``__getattr__``
# so importing this module performs no file I/O.
ZINC_DARK: Theme


def _get_zinc_dark() -> Theme:
    """Resolve the built-in zinc theme lazily on first access."""
    global _ZINC_DARK
    if _ZINC_DARK is None:
        _ZINC_DARK = _ensure_loaded()["zinc"]
    return _ZINC_DARK


def __getattr__(name: str) -> Theme:
    """Resolve ``ZINC_DARK`` on first access so importing the module does no I/O."""
    if name == "ZINC_DARK":
        return _get_zinc_dark()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "DEFAULT_THEME_NAME",
    "ZINC_DARK",
    "get_theme",
    "list_themes",
]
