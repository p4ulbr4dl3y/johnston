"""Theme selection screen for choosing color palettes."""

from typing import Optional

from core.theme_manager import theme_manager
from widgets.presentation.screens.base_modal import status_tag
from widgets.presentation.screens.base_selection import BaseSelectionScreen
from widgets.utils.key_aliases import expand_bindings
from widgets.utils.row_format import MODAL_MEDIUM_ROW_WIDTH, format_badge_row, option_list_row_width


class ThemeScreen(BaseSelectionScreen[Optional[str]]):
    """Modal screen for selecting UI and syntax color theme."""

    BINDINGS = expand_bindings([
        ("escape", "cancel", "Cancel"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ])

    def __init__(self) -> None:
        self.themes = theme_manager.list_themes()
        options, items, default_val = self._build_data()
        super().__init__(
            title="### **Select Theme**",
            options=options,
            items=items,
            default_value=default_val,
            show_search=True,
            search_placeholder="Search themes...",
            hint_text="enter: select • ↑↓: nav • esc: close",
            dialog_classes="modal-dialog-medium",
        )

    def _row_width(self) -> int:
        try:
            opt_list = self.query_one(f"#{self.option_list_id}")
            return option_list_row_width(opt_list, MODAL_MEDIUM_ROW_WIDTH)
        except Exception:
            return option_list_row_width(None, MODAL_MEDIUM_ROW_WIDTH)

    def _build_data(self) -> tuple[list[str], list[str], str]:
        current_name = theme_manager.current_theme.name
        options: list[str] = []
        items: list[str] = []
        target_w = self._row_width()

        for t in self.themes:
            is_active = t.name == current_name
            tag = status_tag("ON" if is_active else "OFF")
            badge = "Dark" if t.dark else "Light"
            row = format_badge_row(
                title=t.label,
                badge=badge,
                prefix=f"{tag}  ",
                target_width=target_w,
            )
            options.append(row)
            items.append(t.name)

        return options, items, current_name
