from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input

from widgets.presentation.screens.base_modal import BaseModalScreen
from widgets.presentation.screens.constants import (
    ESC_HINT_CANCEL,
    MODAL_DIALOG_ID,
    MODAL_HINT_ID,
    TAB_KEYS,
)
from widgets.presentation.widgets.modal_header import ModalHeader
from widgets.presentation.widgets.modal_hint import ModalHint


class RenameSessionScreen(BaseModalScreen[str | None]):
    """Modal screen for renaming a session (/rename)."""

    def __init__(self, current_title: str = ""):
        super().__init__()
        self.current_title = current_title

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID):
            yield ModalHeader("Rename Session", esc_hint="")
            yield Input(
                placeholder="New session title...",
                value=self.current_title,
                id="session-rename-input",
                classes="modal-input",
            )
            yield ModalHint(f"enter: save • {ESC_HINT_CANCEL}", id=MODAL_HINT_ID)

    def on_mount(self) -> None:
        inp = self.query_one("#session-rename-input", Input)
        inp.focus()
        inp.cursor_position = len(inp.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def _on_key(self, event: events.Key) -> None:
        if event.key in TAB_KEYS:
            event.prevent_default()
            event.stop()
            return

    def action_cancel(self) -> None:
        self.dismiss(None)
