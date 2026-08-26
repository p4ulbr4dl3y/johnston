from rich.markup import escape

from widgets.presentation.screens.base_selection import BaseSelectionScreen
from widgets.utils.row_format import MODAL_WIDE_ROW_WIDTH, ellipsize


class ForkScreen(BaseSelectionScreen[int]):
    """Modal session fork screen (/fork)."""

    def __init__(self, user_messages: list[tuple[int, str]]):
        self.user_messages = user_messages
        items = [idx for idx, _ in user_messages]
        default_val = items[-1] if items else -1

        options = []
        for _, text in user_messages:
            clean = " ".join(text.replace("\n", " ").replace("\r", " ").split())
            opt_text = clean or "(empty message)"
            options.append(escape(ellipsize(opt_text, MODAL_WIDE_ROW_WIDTH)))

        super().__init__(
            title="### **Select Message to Fork From**",
            options=options,
            items=items,
            default_value=default_val,
            show_search=False,
            hint_text="enter: fork • ↑↓: nav • esc: cancel",
            dialog_classes="modal-dialog-wide",
            fit_content=True,
        )
