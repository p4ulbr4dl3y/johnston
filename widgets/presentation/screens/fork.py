from rich.markup import escape
from textual import events
from textual.widgets import Input

from widgets.presentation.screens.base_selection import BaseSelectionScreen
from widgets.presentation.screens.constants import MODAL_SEARCH_INPUT
from widgets.utils.row_format import MODAL_DEFAULT_ROW_WIDTH, ellipsize, option_list_row_width

FORK_CURRENT_STATE = -1


class ForkScreen(BaseSelectionScreen[int]):
    """Modal session fork screen (/fork)."""

    def __init__(self, user_messages: list[tuple[int, str]]):
        self.user_messages = user_messages
        items = [idx for idx, _ in user_messages]
        items.append(FORK_CURRENT_STATE)
        default_val = FORK_CURRENT_STATE

        options = self._format_options(MODAL_DEFAULT_ROW_WIDTH)

        super().__init__(
            title="### **Select Message to Fork From**",
            options=options,
            items=items,
            default_value=default_val,
            show_search=True,
            search_placeholder="Search...",
            hint_text="enter: fork • ↑↓: nav • esc: cancel",
        )

    def _row_width(self) -> int:
        try:
            opt_list = self.query_one(f"#{self.option_list_id}")
        except Exception:
            opt_list = self
        return option_list_row_width(opt_list, MODAL_DEFAULT_ROW_WIDTH)

    def _format_options(self, target_width: int) -> list[str]:
        options = []
        for _, text in self.user_messages:
            clean = " ".join(text.replace("\n", " ").replace("\r", " ").split())
            opt_text = clean or "(empty message)"
            options.append(escape(ellipsize(opt_text, max(10, target_width - 2))))
        options.append("Current state [dim](keep full history)[/]")
        return options

    def _refresh_options(self) -> None:
        target_w = self._row_width()
        self.raw_options = self._format_options(target_w)
        query = ""
        if self.show_search:
            try:
                query = self.query_one(MODAL_SEARCH_INPUT, Input).value
            except Exception:
                pass
        self._filter_options(query)

    def on_resize(self, event: events.Resize) -> None:
        super().on_resize(event)
        self._refresh_options()
