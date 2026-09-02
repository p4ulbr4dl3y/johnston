from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Markdown

from widgets.presentation.screens.base_modal import BaseModalScreen
from widgets.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT_ID,
    MODAL_MARKDOWN,
    TAB_KEYS,
)
from widgets.presentation.widgets.modal_header import ModalHeader
from widgets.presentation.widgets.modal_hint import ModalHint
from widgets.utils.key_aliases import normalize_key_to_latin
from widgets.utils.responsive import (
    MODAL_COMPACT_MAX_WIDTH,
    MODAL_MIN_WIDTH,
    apply_modal_fit,
)


class ConfirmScreen(BaseModalScreen[bool]):
    """Generic confirmation modal screen with enter/esc and y/n keys."""

    def __init__(
        self,
        title: str = "Confirm Action",
        message: str = "Are you sure?",
        confirm_label: str = "Confirm",
        cancel_label: str = "Cancel",
    ):
        super().__init__()
        self.confirm_title = title
        self.message = message
        self.confirm_label = confirm_label
        self.cancel_label = cancel_label

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID, classes="modal-dialog-compact"):
            yield ModalHeader(self.confirm_title, esc_hint="")
            if self.message:
                yield Markdown(self.message, classes=MODAL_MARKDOWN)
            yield ModalHint(f"enter {self.confirm_label} • esc {self.cancel_label}", id=MODAL_HINT_ID)

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
        norm_key = normalize_key_to_latin(event.key)
        if norm_key in ("enter", "y"):
            self.dismiss(True)
            event.prevent_default()
            event.stop()
            return
        if norm_key in ("escape", "n"):
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
