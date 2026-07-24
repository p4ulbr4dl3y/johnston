from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Markdown

from widgets.screens.base_selection import BaseSelectionScreen


class ProvidersScreen(BaseSelectionScreen[str]):
    """Modal provider selection screen for /providers command"""

    def __init__(self, providers: dict, active_key: str, configured_keys: dict, disabled_providers: list = None):
        providers_list = list(providers.values())
        disabled_set = set(disabled_providers or [])
        options = []
        items = []

        for p in providers_list:
            key = p["key"]
            name = p["name"]
            has_key = bool(configured_keys.get(key))
            is_active = (key == active_key)
            is_disabled = key in disabled_set or p.get("disabled", False)

            badge = ""
            if is_disabled:
                badge = " [Disabled]"
            elif is_active:
                badge = " [Active]"
            elif has_key:
                badge = " [Configured]"

            options.append(f"{name}{badge}")
            items.append(key)

        super().__init__(
            title="### **Manage AI Providers**",
            options=options,
            items=items,
            default_value=active_key if active_key in items else (items[0] if items else ""),
            show_search=True,
            search_placeholder="Search providers..."
        )


ConnectProviderScreen = ProvidersScreen


class ProviderActionScreen(BaseSelectionScreen[str]):
    """Modal provider action screen (Configure Key vs Toggle Disable)"""

    def __init__(self, provider_name: str, is_disabled: bool = False):
        toggle_label = "Enable Provider" if is_disabled else "Disable Provider"
        options = [
            "1. Configure API Key / Connect",
            f"2. {toggle_label}"
        ]
        items = [
            "connect",
            "toggle_disable"
        ]
        super().__init__(
            title=f"### **Provider Options: {provider_name}**",
            options=options,
            items=items,
            default_value=items[0],
            show_search=False
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
