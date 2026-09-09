from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Markdown

from johnston.tui.presentation.screens.base_modal import BaseModalScreen
from johnston.tui.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT_ID,
    MODAL_MARKDOWN,
    TAB_KEYS,
)
from johnston.tui.presentation.widgets.modal_header import ModalHeader
from johnston.tui.presentation.widgets.modal_hint import ModalHint
from johnston.tui.utils.key_aliases import expand_bindings, normalize_key_to_latin
from johnston.tui.utils.responsive import (
    MODAL_COMPACT_MAX_WIDTH,
    MODAL_MIN_WIDTH,
    apply_modal_fit,
)


class ConfirmScreen(BaseModalScreen[bool]):
    """Generic confirmation modal screen with enter/esc, y/n, and d/c keys."""

    can_focus = True

    BINDINGS = expand_bindings([
        ("enter", "confirm", "Confirm"),
        ("y", "confirm", "Yes"),
        ("d", "confirm", "Delete"),
        ("delete", "confirm", "Delete"),
        ("escape", "cancel", "Cancel"),
        ("n", "cancel", "No"),
        ("c", "cancel", "Cancel"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ])

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
        try:
            self.focus()
        except Exception:
            pass

    def on_resize(self, event: events.Resize) -> None:
        self._apply_dialog_fit()

    def action_confirm(self) -> None:
        self.dismiss(True)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def _on_key(self, event: events.Key) -> None:
        norm_key = normalize_key_to_latin(event.key)
        if norm_key in ("enter", "y", "d", "delete"):
            self.dismiss(True)
            event.prevent_default()
            event.stop()
            return
        if norm_key in ("escape", "n", "c"):
            self.dismiss(False)
            event.prevent_default()
            event.stop()
            return
        if event.key in TAB_KEYS:
            event.prevent_default()
            event.stop()
            return

    def on_click(self, event: events.Click) -> None:
        try:
            dialog = self.query_one(f"#{MODAL_DIALOG_ID}")
            if not dialog.region.contains(event.screen_x, event.screen_y):
                self.dismiss(False)
        except Exception:
            pass
