"""Theme selection screen with live preview, search filter, and fit-content modal."""

from textual.widgets import OptionList

from widgets.app.theme_manager import theme_manager
from widgets.presentation.screens.base_modal import status_tag
from widgets.presentation.screens.base_selection import BaseSelectionScreen
from widgets.presentation.screens.constants import ESC_HINT_CLOSE


class ThemeScreen(BaseSelectionScreen[str]):
    """Modal screen for selecting UI color themes with search, live preview, and compact fit."""

    def __init__(self, current_theme: str | None = None) -> None:
        current = current_theme or theme_manager.current_theme.name
        self.initial_theme = current
        self._preview_timer = None
        self._pending_theme = None
        themes = sorted(theme_manager.list_themes(), key=lambda t: not t.dark)
        items = [t.name for t in themes]
        options = []
        for t in themes:
            prefix = f"{status_tag('ACTIVE')} " if t.name == current else "  "
            options.append(f"{prefix}{t.label}")
        super().__init__(
            title="### **Select Theme**",
            options=options,
            items=items,
            default_value=current,
            show_search=True,
            search_placeholder="Search themes...",
            hint_text=f"enter: select • {ESC_HINT_CLOSE}",
            fit_content=True,
        )

    def _apply_preview(self) -> None:
        if self._pending_theme and hasattr(self.app, "set_app_theme") and getattr(self, "is_mounted", True):
            self.app.set_app_theme(self._pending_theme, persist=False)

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        """Live preview theme as user scrolls or searches with light debouncing."""
        if event.option_index is not None and 0 <= event.option_index < len(self.filtered_items):
            preview_theme = self.filtered_items[event.option_index]
            if preview_theme:
                self._pending_theme = preview_theme
                if self._preview_timer is not None:
                    try:
                        self._preview_timer.stop()
                    except Exception:
                        pass
                self._preview_timer = self.set_timer(0.05, self._apply_preview)

    def action_cancel(self) -> None:
        """Revert back to initial theme on Escape / cancel."""
        if self._preview_timer is not None:
            try:
                self._preview_timer.stop()
            except Exception:
                pass
        if hasattr(self.app, "set_app_theme"):
            self.app.set_app_theme(self.initial_theme, persist=False)
        super().action_cancel()
