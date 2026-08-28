"""Core theme registry and lifecycle manager for Johnston."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable, Optional

from core.domain.defaults.themes import BUILTIN_THEMES, ZINC_DARK
from core.domain.entities.theme import Theme
from core.infrastructure.config.config_helpers import load_theme_config, save_theme_config
from core.infrastructure.platform.paths import THEMES_DIR
from core.infrastructure.platform.platform_utils import read_json

logger = logging.getLogger(__name__)


class ThemeManager:
    """Registry and state manager for UI themes and syntax palettes."""

    _instance: Optional[ThemeManager] = None

    def __init__(
        self,
        default_theme: str = "zinc",
        load_config: bool = True,
        load_custom_themes: bool = True,
        custom_themes_dir: Optional[str | Path] = None,
    ) -> None:
        self._themes: dict[str, Theme] = {}
        self._listeners: list[Callable[[Theme], None]] = []

        for theme in BUILTIN_THEMES:
            self.register(theme)

        if load_custom_themes:
            self.load_user_themes(custom_themes_dir)

        chosen = default_theme
        if load_config:
            try:
                saved = load_theme_config()
                if saved and saved in self._themes:
                    chosen = saved
            except Exception as e:
                logger.warning("Failed to load theme config: %s", e)

        self._current_theme: Theme = self._themes.get(chosen, ZINC_DARK)

    @classmethod
    def get_instance(cls) -> ThemeManager:
        """Get or initialize singleton ThemeManager instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (primarily for testing)."""
        cls._instance = None

    def load_user_themes(self, themes_dir: Optional[str | Path] = None) -> list[Theme]:
        """Load and register user-defined themes from JSON files in themes_dir."""
        target_dir = Path(themes_dir or THEMES_DIR)
        loaded: list[Theme] = []
        if not target_dir.exists() or not target_dir.is_dir():
            return loaded

        for file_path in sorted(target_dir.glob("*.json")):
            try:
                data = read_json(str(file_path), default=None)
                if isinstance(data, dict):
                    user_theme = Theme.from_dict(data)
                    self.register(user_theme)
                    loaded.append(user_theme)
                    logger.info("Loaded custom theme '%s' from %s", user_theme.name, file_path)
            except Exception as e:
                logger.warning("Failed to load custom theme from %s: %s", file_path, e)

        return loaded

    def register(self, theme: Theme) -> None:
        """Register a theme instance into the registry."""
        self._themes[theme.name] = theme

    def get(self, name: str) -> Optional[Theme]:
        """Retrieve theme by name."""
        return self._themes.get(name)

    def list_themes(self) -> list[Theme]:
        """List all registered themes."""
        return list(self._themes.values())

    @property
    def current_theme(self) -> Theme:
        """Get the currently active theme."""
        return self._current_theme

    def set_theme(self, name: str, persist: bool = True) -> Theme:
        """Set active theme by name, optionally persisting to config and notifying listeners."""
        theme = self._themes.get(name)
        if not theme:
            raise ValueError(f"Unknown theme: {name}. Available: {list(self._themes.keys())}")
        self._current_theme = theme

        if persist:
            try:
                save_theme_config(theme.name)
            except Exception as e:
                logger.warning("Failed to persist theme config: %s", e)

        for listener in list(self._listeners):
            try:
                listener(theme)
            except Exception as e:
                logger.warning("Theme listener error: %s", e)
        return theme

    def add_listener(self, listener: Callable[[Theme], None]) -> None:
        """Subscribe listener callback to theme changes."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[Theme], None]) -> None:
        """Unsubscribe listener callback."""
        if listener in self._listeners:
            self._listeners.remove(listener)


theme_manager = ThemeManager.get_instance()
