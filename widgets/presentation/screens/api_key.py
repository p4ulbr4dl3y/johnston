from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Markdown

from widgets.presentation.screens.base_modal import BaseModalScreen
from widgets.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT_ID,
    MODAL_MARKDOWN,
    MODAL_MARKDOWN_CENTERED,
    TAB_KEYS,
)
from widgets.presentation.widgets.modal_hint import ModalHint
from widgets.utils.responsive import (
    MODAL_COMPACT_MAX_WIDTH,
    MODAL_MIN_WIDTH,
    apply_modal_fit,
)


class ApiKeyScreen(BaseModalScreen[str | None]):
    """Compact modal screen for entering or updating a provider API key."""

    def __init__(
        self,
        provider_name: str,
        current_key: str = "",
        provider_key: str = "",
    ):
        super().__init__()
        self.provider_name = provider_name
        self.current_key = current_key
        self.provider_key = provider_key

    def compose(self) -> ComposeResult:
        if self.current_key:
            if len(self.current_key) > 8:
                masked = f"{self.current_key[:4]}...{self.current_key[-4:]}"
            else:
                masked = self.current_key
            placeholder = masked
        else:
            placeholder = "API Key..."

        with Vertical(id=MODAL_DIALOG_ID, classes="modal-dialog-compact"):
            yield Markdown(f"### **Connect {self.provider_name}**", classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}")
            yield Input(placeholder=placeholder, password=True, id="providers-key-input")
            yield ModalHint("enter: save • esc: cancel", id=MODAL_HINT_ID)

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
            inp = self.query_one("#providers-key-input", Input)
            inp.focus()
        except Exception:
            pass

    def on_resize(self, event: events.Resize) -> None:
        self._apply_dialog_fit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        event.prevent_default()
        val = event.value.strip()
        final_val = val if val else self.current_key
        self.dismiss(final_val)

    def _on_key(self, event: events.Key) -> None:
        if event.key == "escape":
            self.dismiss(None)
            event.prevent_default()
            event.stop()
            return
        if event.key in TAB_KEYS:
            event.prevent_default()
            event.stop()
            return

    def action_cancel(self) -> None:
        self.dismiss(None)
