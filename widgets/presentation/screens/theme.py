"""Theme selection screen with live preview and confirm-on-enter design."""

from textual.widgets import OptionList

from core.theme_manager import theme_manager
from widgets.presentation.screens.base_modal import status_tag
from widgets.presentation.screens.base_selection import BaseSelectionScreen


class ThemeScreen(BaseSelectionScreen[str]):
    """Compact content-hugging modal screen with live theme preview on navigation."""

    def __init__(self, current_theme: str | None = None) -> None:
        current = current_theme or theme_manager.current_theme.name
        self.initial_theme = current
        themes = theme_manager.list_themes()
        items = [t.name for t in themes]
        options = []
        for t in themes:
            prefix = f"{status_tag('ACTIVE')} " if t.name == current else "  "
            options.append(f"{prefix}{t.label}")
        super().__init__(
            "### **Select Theme**",
            options,
            items,
            current,
            show_search=False,
            fit_content=True,
        )

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        """Live preview theme as user scrolls/navigates options without persisting."""
        if event.option_index is not None and 0 <= event.option_index < len(self.raw_items):
            preview_theme = self.raw_items[event.option_index]
            if hasattr(self.app, "set_app_theme"):
                self.app.set_app_theme(preview_theme, persist=False)

    def action_cancel(self) -> None:
        """Revert back to initial theme on Escape / cancel."""
        if hasattr(self.app, "set_app_theme"):
            self.app.set_app_theme(self.initial_theme, persist=False)
        super().action_cancel()
