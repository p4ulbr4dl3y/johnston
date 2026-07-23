from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Markdown

from widgets.screens.base_selection import BaseSelectionScreen


class ConnectProviderScreen(BaseSelectionScreen[str]):
    """Modal provider selection screen for /connect command"""

    def __init__(self, providers: dict, active_key: str, configured_keys: dict):
        providers_list = list(providers.values())
        options = []
        items = []

        for p in providers_list:
            key = p["key"]
            name = p["name"]
            has_key = bool(configured_keys.get(key))
            is_active = (key == active_key)

            badge = ""
            if is_active:
                badge = " [Active]"
            elif has_key:
                badge = " [Configured]"

            options.append(f"{name}{badge}")
            items.append(key)

        super().__init__(
            title="### **Select AI provider to connect**",
            options=options,
            items=items,
            default_value=active_key if active_key in items else (items[0] if items else "")
        )


class ApiKeyInputScreen(ModalScreen[str | None]):
    """Modal API key input screen"""
    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, provider_name: str, provider_key: str, current_key: str = ""):
        super().__init__()
        self.provider_name = provider_name
        self.provider_key = provider_key
        self.current_key = current_key

    def compose(self) -> ComposeResult:
        if self.current_key and len(self.current_key) > 8:
            masked = f"{self.current_key[:4]}...{self.current_key[-4:]}"
        else:
            masked = self.current_key if self.current_key else "not set"

        with Vertical(id="modal-dialog"):
            yield Markdown(
                f"### **Connect {self.provider_name}**\n\n"
                f"Current API Key: `{masked}`",
                classes="modal-markdown"
            )
            yield Input(placeholder="API Key...", value="", password=True, id="api-key-input")
            yield Label("enter: save • esc: cancel", id="modal-hint")

    def on_mount(self) -> None:
        self.query_one("#api-key-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def action_cancel(self) -> None:
        self.dismiss(None)
