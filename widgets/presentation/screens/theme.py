"""Theme selection screen matching thinking effort modal design."""

from core.theme_manager import theme_manager
from widgets.presentation.screens.base_modal import status_tag
from widgets.presentation.screens.base_selection import BaseSelectionScreen


class ThemeScreen(BaseSelectionScreen[str]):
    """Compact content-hugging modal screen for selecting UI color themes."""

    def __init__(self, current_theme: str | None = None) -> None:
        current = current_theme or theme_manager.current_theme.name
        items_with_hints = [
            ("zinc", "Zinc Dark", "default monochrome"),
            ("dracula", "Dracula", "classic vampire theme"),
            ("catppuccin-mocha", "Catppuccin Mocha", "soothing dark"),
            ("tokyo-night", "Tokyo Night", "vibrant dark"),
            ("nord", "Nord", "arctic dark"),
            ("zinc-light", "Zinc Light", "clean light theme"),
        ]
        items = [item for item, _, _ in items_with_hints]
        options = []
        for item, label, hint in items_with_hints:
            prefix = f"{status_tag('ACTIVE')} " if item == current else "  "
            options.append(f"{prefix}{label} [dim #71717a]({hint})[/]")
        super().__init__(
            "### **Select Theme**",
            options,
            items,
            current,
            show_search=False,
            fit_content=True,
        )
