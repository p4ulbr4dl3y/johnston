from rich.markup import escape
from textual import events
from textual.widgets import OptionList

from widgets.presentation.screens.base_selection import BaseSelectionScreen
from widgets.presentation.screens.constants import MODAL_OPTION_LIST
from widgets.utils.row_format import MODAL_MEDIUM_ROW_WIDTH, ellipsize, option_list_row_width


class ForkScreen(BaseSelectionScreen[int]):
    """Modal session fork screen (/fork)."""

    def __init__(self, user_messages: list[tuple[int, str]]):
        self.user_messages = user_messages
        items = [idx for idx, _ in user_messages]
        default_val = items[-1] if items else -1

        options = self._format_all_options(MODAL_MEDIUM_ROW_WIDTH)

        super().__init__(
            title="### **Select Message to Fork From**",
            options=options,
            items=items,
            default_value=default_val,
            show_search=False,
            hint_text="enter: fork • ↑↓: nav • esc: cancel",
            dialog_classes="modal-dialog-medium",
        )

    def _row_width(self) -> int:
        try:
            opt_list = self.query_one(MODAL_OPTION_LIST, OptionList)
        except Exception:
            opt_list = self
        return option_list_row_width(opt_list, MODAL_MEDIUM_ROW_WIDTH)

    def _format_all_options(self, target_width: int) -> list[str]:
        options = []
        for _, text in self.user_messages:
            clean = " ".join(text.replace("\n", " ").replace("\r", " ").split())
            opt_text = clean or "(empty message)"
            options.append(escape(ellipsize(opt_text, max(10, target_width - 5))))
        return options

    def _refresh_options(self) -> None:
        target_w = self._row_width()
        self.raw_options = self._format_all_options(target_w)
        self.filtered_options = list(self.raw_options)
        try:
            opt_list = self.query_one(MODAL_OPTION_LIST, OptionList)
            saved_idx = opt_list.highlighted
            opt_list.clear_options()
            opt_list.add_options(self.filtered_options)
            if saved_idx is not None and 0 <= saved_idx < len(self.filtered_options):
                opt_list.highlighted = saved_idx
        except Exception:
            pass

    def on_mount(self) -> None:
        super().on_mount()
        self._refresh_options()

    def on_resize(self, event: events.Resize) -> None:
        super().on_resize(event)
        self._refresh_options()
