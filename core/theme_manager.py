"""Unified theme manager for Johnston."""

from __future__ import annotations

import logging
from typing import Callable, Optional

from textual.theme import Theme as TextualTheme

from core.domain.defaults.themes import BUILTIN_THEMES, ZINC_DARK
from core.domain.entities.theme import Theme

logger = logging.getLogger(__name__)


class ThemeManager:
    """Registry and state manager for UI themes and syntax palettes."""

    _instance: Optional[ThemeManager] = None

    def __init__(self, default_theme: str = "dracula") -> None:
        self._themes: dict[str, Theme] = {}
        self._listeners: list[Callable[[Theme], None]] = []
        for theme in BUILTIN_THEMES:
            self.register(theme)
        self._current_theme: Theme = self._themes.get(default_theme, ZINC_DARK)

    @classmethod
    def get_instance(cls) -> ThemeManager:
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def register(self, theme: Theme) -> None:
        self._themes[theme.name] = theme

    def get(self, name: str) -> Optional[Theme]:
        return self._themes.get(name)

    def list_themes(self) -> list[Theme]:
        return list(self._themes.values())

    @property
    def current_theme(self) -> Theme:
        return self._current_theme

    def set_theme(self, name: str) -> Theme:
        theme = self._themes.get(name)
        if not theme:
            raise ValueError(f"Unknown theme: {name}. Available: {list(self._themes.keys())}")
        self._current_theme = theme
        for listener in list(self._listeners):
            try:
                listener(theme)
            except Exception as e:
                logger.warning("Theme listener error: %s", e)
        return theme

    def add_listener(self, listener: Callable[[Theme], None]) -> None:
        if listener not in self._listeners:
            self._listeners.append(listener)

    def remove_listener(self, listener: Callable[[Theme], None]) -> None:
        if listener in self._listeners:
            self._listeners.remove(listener)

    def get_textual_theme(self, theme_or_name: str | Theme) -> TextualTheme:
        theme = theme_or_name if isinstance(theme_or_name, Theme) else self._themes.get(theme_or_name, ZINC_DARK)
        tcss_vars = dict(theme.tcss_vars)
        return TextualTheme(
            name=theme.name,
            primary=theme.primary,
            secondary=theme.secondary,
            background=tcss_vars.get("bg-app", "#09090b"),
            surface=tcss_vars.get("bg-surface", "#18181b"),
            dark=theme.dark,
            variables=tcss_vars,
        )

    def get_all_textual_themes(self) -> list[TextualTheme]:
        return [self.get_textual_theme(t) for t in self._themes.values()]


theme_manager = ThemeManager.get_instance()
