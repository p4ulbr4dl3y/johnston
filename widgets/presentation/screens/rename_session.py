from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Markdown

from widgets.presentation.screens.base_modal import BaseModalScreen
from widgets.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT_ID,
    MODAL_MARKDOWN,
    MODAL_MARKDOWN_CENTERED,
    TAB_KEYS,
)


class RenameSessionScreen(BaseModalScreen[str | None]):
    """Modal screen for renaming a session (/rename)."""

    def __init__(self, current_title: str = ""):
        super().__init__()
        self.current_title = current_title

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID):
            yield Markdown("### **Rename Session**", classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}")
            yield Input(
                placeholder="New session title...",
                value=self.current_title,
                id="session-rename-input",
            )
            yield Label("enter: save • esc: cancel", id=MODAL_HINT_ID)

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
