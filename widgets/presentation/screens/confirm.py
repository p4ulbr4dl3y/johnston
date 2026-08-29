from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, Markdown

from widgets.presentation.screens.base_modal import BaseModalScreen
from widgets.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT_ID,
    MODAL_MARKDOWN,
    MODAL_MARKDOWN_CENTERED,
    TAB_KEYS,
)
from widgets.utils.responsive import (
    MODAL_COMPACT_MAX_WIDTH,
    MODAL_MIN_WIDTH,
    apply_modal_fit,
)


class ConfirmScreen(BaseModalScreen[bool]):
    """Generic confirmation modal screen with enter/esc and y/n keys."""

    def __init__(
        self,
        title: str = "### **Confirm Action**",
        message: str = "Are you sure?",
        confirm_label: str = "confirm",
        cancel_label: str = "cancel",
    ):
        super().__init__()
        self.confirm_title = title
        self.message = message
        self.confirm_label = confirm_label
        self.cancel_label = cancel_label

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID, classes="modal-dialog-compact"):
            yield Markdown(self.confirm_title, classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}")
            if self.message:
                yield Markdown(self.message, classes=MODAL_MARKDOWN)
            yield Label(f"enter: {self.confirm_label} • esc: {self.cancel_label}", id=MODAL_HINT_ID)

    def _apply_dialog_fit(self) -> None:
        try:
            dialog = self.query_one(f"#{MODAL_DIALOG_ID}")
            apply_modal_fit(
                dialog,
                MODAL_COMPACT_MAX_WIDTH,
                min_width=MODAL_MIN_WIDTH,
                max_width=MODAL_COMPACT_MAX_WIDTH,
            )
        except Exception:
            pass

    def on_mount(self) -> None:
        super().on_mount()
        self._apply_dialog_fit()

    def on_resize(self, event: events.Resize) -> None:
        self._apply_dialog_fit()

    def _on_key(self, event: events.Key) -> None:
        if event.key in ("enter", "y", "Y"):
            self.dismiss(True)
            event.prevent_default()
            event.stop()
            return
        if event.key in ("escape", "n", "N"):
            self.dismiss(False)
            event.prevent_default()
            event.stop()
            return
        if event.key in TAB_KEYS:
            event.prevent_default()
            event.stop()
            return

    def action_cancel(self) -> None:
        self.dismiss(False)
