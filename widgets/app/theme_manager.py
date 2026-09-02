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

    def _adapt_theme(self, theme: Theme) -> Theme:
        """Adapt a native theme to the runtime terminal environment before use."""
        if theme.name == "native":
            return self.get_adapted_theme(theme)
        return theme

    def get_adapted_theme(self, theme_or_name: str | Theme) -> Theme:
        """Return theme adapted to runtime terminal environment if applicable."""
        theme = theme_or_name if isinstance(theme_or_name, Theme) else self._themes.get(theme_or_name, ZINC_DARK)
        tcss_vars = dict(theme.tcss_vars)
        bg_app = tcss_vars.get("bg-app", "#09090b")
        is_ansi = bg_app in ("ansi_default", "transparent") or theme.name == "native"
        if not is_ansi:
            return theme

        from core.infrastructure.platform.terminal_theme import (
            compute_adaptive_palette,
            query_terminal_palette,
        )

        detected_bg, detected_fg = query_terminal_palette()
        palette = compute_adaptive_palette(detected_bg, detected_fg)
        adapted_tcss = dict(tcss_vars)
        adapted_tcss.update(palette["tcss_vars"])
        adapted_tcss["bg-overlay"] = "transparent"

        if not palette["dark"]:
            from core.domain.defaults.themes import get_theme

            latte = get_theme("catppuccin-latte")
            md_styles = dict(latte.markdown_styles) if latte else dict(theme.markdown_styles)
            syntax_tokens = latte.syntax_tokens if latte else theme.syntax_tokens
        else:
            md_styles = dict(theme.markdown_styles)
            syntax_tokens = theme.syntax_tokens

        md_styles["markdown.paragraph"] = palette["fg_primary"]
        md_styles["markdown.text"] = palette["fg_primary"]
        md_styles["markdown.item"] = palette["fg_primary"]
        md_styles["markdown.em"] = f"italic {palette['fg_primary']}"
        md_styles["markdown.code"] = f"{palette['fg_primary']} on {palette['bg_surface']}"

        return Theme(
            name=theme.name,
            label=theme.label,
            dark=palette["dark"],
            primary=palette["primary"],
            secondary=palette["secondary"],
            muted=palette["muted"],
            subtle=palette["subtle"],
            tcss_vars=adapted_tcss,
            markdown_styles=md_styles,
            syntax_tokens=syntax_tokens,
        )

    def get_textual_theme(self, theme_or_name: str | Theme) -> TextualTheme:
        """Convert Johnston Theme to TextualTheme instance."""
        adapted = self.get_adapted_theme(theme_or_name)
        tcss_vars = dict(adapted.tcss_vars)
        bg_app = tcss_vars.get("bg-app", "#09090b")
        is_ansi = bg_app in ("ansi_default", "transparent") or adapted.name == "native"
        return TextualTheme(
            name=adapted.name,
            primary=adapted.primary,
            secondary=adapted.secondary,
            foreground=tcss_vars.get("fg-primary", "#ffffff" if adapted.dark else "#18181b"),
            background=bg_app,
            surface=tcss_vars.get("bg-surface", "#18181b"),
            dark=adapted.dark,
            ansi=is_ansi,
            variables=tcss_vars,
        )

    def get_all_textual_themes(self) -> list[TextualTheme]:
        """Get all registered themes converted to TextualTheme instances."""
        return [self.get_textual_theme(t) for t in self._themes.values()]


theme_manager = ThemeManager.get_instance()

