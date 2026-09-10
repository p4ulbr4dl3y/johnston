"""Core theme registry and lifecycle manager for Johnston."""

from __future__ import annotations

import inspect
import logging
import weakref
from pathlib import Path
from typing import Any, Callable, Optional

from johnston.tui.adapters import core_bridge

ZINC_DARK = core_bridge.get_theme_vars()
list_themes = core_bridge.list_themes
Theme = core_bridge.get_theme_class()

logger = logging.getLogger(__name__)


class BaseThemeManager:
    """Registry and state manager for UI themes and syntax palettes."""

    _instance: Optional[BaseThemeManager] = None

    def __init__(
        self,
        default_theme: str = "zinc",
        load_config: bool = True,
        load_custom_themes: bool = True,
        custom_themes_dir: Optional[str | Path] = None,
    ) -> None:
        self._themes: dict[str, Theme] = {}
        self._listeners: list[Callable[[Theme], None]] = []

        for theme in list_themes():
            self.register(theme)

        if load_custom_themes:
            self.load_user_themes(custom_themes_dir)

        chosen = default_theme
        if load_config:
            try:
                saved = core_bridge.load_theme_config()
                if saved and saved in self._themes:
                    chosen = saved
            except Exception as e:
                logger.warning("Failed to load theme config: %s", e)

        self._current_theme: Theme = self._themes.get(chosen, ZINC_DARK)

    @classmethod
    def get_instance(cls) -> BaseThemeManager:
        """Get or initialize singleton BaseThemeManager instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (primarily for testing)."""
        cls._instance = None

    def load_user_themes(self, themes_dir: Optional[str | Path] = None) -> list[Theme]:
        """Load and register user-defined themes from JSON files in themes_dir."""
        target_dir = Path(themes_dir or core_bridge.THEMES_DIR)
        loaded: list[Theme] = []
        if not target_dir.exists() or not target_dir.is_dir():
            return loaded

        for file_path in sorted(target_dir.glob("*.json")):
            try:
                data = core_bridge.read_json(str(file_path), default=None)
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

    def _adapt_theme(self, theme: Theme) -> Theme:
        """Extensible hook for subclasses to adapt a theme before it is returned/notified."""
        return theme

    @property
    def current_theme(self) -> Theme:
        """Get the currently active theme."""
        return self._adapt_theme(self._current_theme)

    def _unwrap_listener(self, ref: Any) -> Optional[Callable[[Theme], None]]:
        if isinstance(ref, (weakref.ReferenceType, weakref.WeakMethod)):
            return ref()
        return ref

    def set_theme(self, name: str, persist: bool = True) -> Theme:
        """Set active theme by name, optionally persisting to config and notifying listeners."""
        theme = self._themes.get(name)
        if not theme:
            raise ValueError(f"Unknown theme: {name}. Available: {list(self._themes.keys())}")
        self._current_theme = theme

        if persist:
            try:
                core_bridge.save_theme_config(theme.name)
            except Exception as e:
                logger.warning("Failed to persist theme config: %s", e)

        active_theme = self._adapt_theme(theme)
        alive_listeners = []
        for ref in self._listeners:
            callback = self._unwrap_listener(ref)
            if callback is not None:
                alive_listeners.append(ref)
                try:
                    callback(active_theme)
                except Exception as e:
                    logger.warning("Theme listener error: %s", e)
        self._listeners = alive_listeners
        return active_theme

    def add_listener(self, listener: Callable[[Theme], None]) -> None:
        """Subscribe listener callback to theme changes (using weak references for methods)."""
        alive_listeners = []
        for ref in self._listeners:
            cb = self._unwrap_listener(ref)
            if cb is not None:
                if cb == listener:
                    return
                alive_listeners.append(ref)
        self._listeners = alive_listeners

        if inspect.ismethod(listener):
            try:
                self._listeners.append(weakref.WeakMethod(listener))
                return
            except TypeError:
                pass
        self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[Theme], None]) -> None:
        """Safely unsubscribe listener callback."""
        alive_listeners = []
        for ref in self._listeners:
            cb = self._unwrap_listener(ref)
            if cb is not None and cb != listener:
                alive_listeners.append(ref)
        self._listeners = alive_listeners


ThemeManager = BaseThemeManager
