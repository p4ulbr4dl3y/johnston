"""Theme and styling constants and helpers for TUI presentation layer."""
from __future__ import annotations

from typing import Any

from johnston.core.domain.defaults.config import (
    COLOR_DIFF_ADD_BG,
    COLOR_DIFF_ADD_FG,
    COLOR_DIFF_GUTTER,
    COLOR_DIFF_REMOVE_BG,
    COLOR_DIFF_REMOVE_FG,
    COLOR_STATUS_ERROR,
    COLOR_STATUS_RUNNING,
    COLOR_STATUS_SUCCESS,
    THEME_MUTED,
    THEME_PRIMARY,
    THEME_SECONDARY,
    THEME_SUBTLE,
)
from johnston.core.infrastructure.platform.paths import THEMES_DIR


def get_theme_variable_defaults() -> dict[str, str]:
    """Return design-token defaults from the default theme."""
    from johnston.core.domain.defaults.themes import ZINC_DARK

    return dict(ZINC_DARK.tcss_vars)


def load_theme_config() -> Any:
    """Load the active theme config."""
    from johnston.core.infrastructure.config.config_helpers import (
        load_theme_config as _f,
    )

    return _f()


def save_theme_config(theme_name: str) -> None:
    """Persist the active theme config."""
    from johnston.core.infrastructure.config.config_helpers import (
        save_theme_config as _f,
    )

    _f(theme_name)


def get_theme_constants() -> dict[str, Any]:
    """Theme/status color constants from domain defaults."""
    return dict(
        COLOR_DIFF_ADD_BG=COLOR_DIFF_ADD_BG,
        COLOR_DIFF_ADD_FG=COLOR_DIFF_ADD_FG,
        COLOR_DIFF_GUTTER=COLOR_DIFF_GUTTER,
        COLOR_DIFF_REMOVE_BG=COLOR_DIFF_REMOVE_BG,
        COLOR_DIFF_REMOVE_FG=COLOR_DIFF_REMOVE_FG,
        COLOR_STATUS_ERROR=COLOR_STATUS_ERROR,
        COLOR_STATUS_RUNNING=COLOR_STATUS_RUNNING,
        COLOR_STATUS_SUCCESS=COLOR_STATUS_SUCCESS,
        THEME_MUTED=THEME_MUTED,
        THEME_PRIMARY=THEME_PRIMARY,
        THEME_SECONDARY=THEME_SECONDARY,
        THEME_SUBTLE=THEME_SUBTLE,
    )


def get_theme_vars() -> Any:
    """Design tokens used by the markdown/theme layer."""
    from johnston.core.domain.defaults.themes import ZINC_DARK as _f

    return _f


def list_themes() -> Any:
    """List available themes."""
    import johnston.core.domain.defaults.themes as _m

    return _m.list_themes()


def get_theme_by_name(name: str) -> Any:
    """Resolve a theme by name."""
    import johnston.core.domain.defaults.themes as _m

    return _m.get_theme(name)


def is_ansi_theme(theme: Any) -> bool:
    """Whether a theme is ANSI-based."""
    from johnston.core.domain.entities.theme import is_ansi_theme as _f

    return _f(theme)


def get_theme_class() -> Any:
    """Theme entity class."""
    from johnston.core.domain.entities.theme import Theme as _f

    return _f


__all__ = [
    "COLOR_DIFF_ADD_BG",
    "COLOR_DIFF_ADD_FG",
    "COLOR_DIFF_GUTTER",
    "COLOR_DIFF_REMOVE_BG",
    "COLOR_DIFF_REMOVE_FG",
    "COLOR_STATUS_ERROR",
    "COLOR_STATUS_RUNNING",
    "COLOR_STATUS_SUCCESS",
    "THEME_MUTED",
    "THEME_PRIMARY",
    "THEME_SECONDARY",
    "THEME_SUBTLE",
    "THEMES_DIR",
    "get_theme_by_name",
    "get_theme_class",
    "get_theme_constants",
    "get_theme_variable_defaults",
    "get_theme_vars",
    "is_ansi_theme",
    "list_themes",
    "load_theme_config",
    "save_theme_config",
]
