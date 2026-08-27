"""Theme selection screen matching thinking effort modal design."""

from core.theme_manager import theme_manager
from widgets.presentation.screens.base_modal import status_tag
from widgets.presentation.screens.base_selection import BaseSelectionScreen


class ThemeScreen(BaseSelectionScreen[str]):
    """Compact content-hugging modal screen for selecting UI color themes."""

    def __init__(self, current_theme: str | None = None) -> None:
        current = current_theme or theme_manager.current_theme.name
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
