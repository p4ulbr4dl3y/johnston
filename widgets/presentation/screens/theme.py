"""Theme selection screen matching thinking effort modal design."""

from core.theme_manager import theme_manager
from widgets.presentation.screens.base_modal import status_tag
from widgets.presentation.screens.base_selection import BaseSelectionScreen


class ThemeScreen(BaseSelectionScreen[str]):
    """Compact content-hugging modal screen for selecting UI color themes."""

    def __init__(self, current_theme: str | None = None) -> None:
        current = current_theme or theme_manager.current_theme.name
        theme_items = [
            ("zinc", "Zinc Dark"),
            ("dracula", "Dracula"),
            ("catppuccin-mocha", "Catppuccin Mocha"),
            ("tokyo-night", "Tokyo Night"),
            ("nord", "Nord"),
            ("zinc-light", "Zinc Light"),
        ]
        items = [item for item, _ in theme_items]
        options = []
        for item, label in theme_items:
            prefix = f"{status_tag('ACTIVE')} " if item == current else "  "
            options.append(f"{prefix}{label}")
        super().__init__(
            "### **Select Theme**",
            options,
            items,
            current,
            show_search=False,
            fit_content=True,
        )
