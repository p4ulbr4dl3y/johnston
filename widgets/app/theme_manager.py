"""Unified UI theme manager and Textual bridge for Johnston."""

from __future__ import annotations

from typing import Optional

from textual.theme import Theme as TextualTheme

from core.domain.defaults.themes import ZINC_DARK
from core.domain.entities.theme import Theme
from core.theme_manager import ThemeManager as CoreThemeManager


class ThemeManager(CoreThemeManager):
    """UI theme manager extending core registry with Textual Theme conversions."""

    _instance: Optional[ThemeManager] = None

    def get_textual_theme(self, theme_or_name: str | Theme) -> TextualTheme:
        """Convert Johnston Theme to TextualTheme instance."""
        theme = theme_or_name if isinstance(theme_or_name, Theme) else self._themes.get(theme_or_name, ZINC_DARK)
        tcss_vars = dict(theme.tcss_vars)
        bg_app = tcss_vars.get("bg-app", "#09090b")
        is_ansi = bg_app in ("ansi_default", "transparent")
        if is_ansi:
            from core.infrastructure.platform.terminal_theme import (
                compute_adaptive_border,
                compute_adaptive_surface,
                query_terminal_palette,
            )

            detected_bg, _ = query_terminal_palette()
            surface = compute_adaptive_surface(detected_bg)
            border = compute_adaptive_border(detected_bg)
            tcss_vars["bg-surface"] = surface
            tcss_vars["border"] = border
            if "ansi-background" not in tcss_vars:
                tcss_vars["ansi-background"] = "ansi_default"
        return TextualTheme(
            name=theme.name,
            primary=theme.primary,
            secondary=theme.secondary,
            foreground=tcss_vars.get("fg-primary", "#ffffff" if theme.dark else "#18181b"),
            background=bg_app,
            surface=tcss_vars.get("bg-surface", "#18181b"),
            dark=theme.dark,
            ansi=is_ansi,
            variables=tcss_vars,
        )

    def get_all_textual_themes(self) -> list[TextualTheme]:
        """Get all registered themes converted to TextualTheme instances."""
        return [self.get_textual_theme(t) for t in self._themes.values()]


theme_manager = ThemeManager.get_instance()
