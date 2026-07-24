from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Markdown, OptionList

from widgets.screens.base_selection import BaseSelectionScreen


class ProvidersScreen(BaseSelectionScreen[str]):
    """Modal provider selection screen for /providers command with MCP-style [] status tags"""

    def __init__(self, providers: dict, active_key: str, configured_keys: dict, disabled_providers: list = None, pm=None):
        self.providers = providers
        self.active_key = active_key
        self.configured_keys = configured_keys
        self.disabled_set = set(disabled_providers or [])
        self.pm = pm

        options, items = self._build_options()
        super().__init__(
            title="### **Manage AI Providers**",
            options=options,
            items=items,
            default_value=active_key if active_key in items else (items[0] if items else ""),
            show_search=True,
            search_placeholder="Search providers..."
        )

    def _build_options(self):
        options = []
        items = []
        for p in self.providers.values():
            key = p["key"]
            name = p["name"]
            has_key = bool(self.configured_keys.get(key))
            is_active = (key == self.active_key)
            is_disabled = key in self.disabled_set or p.get("disabled", False)

            if is_disabled:
                status_tag = r"\[OFF]"
            elif is_active:
                status_tag = r"\[ACTIVE]"
            elif has_key or key == "opencode":
                status_tag = r"\[ON]"
            else:
                status_tag = r"\[AUTH]"

            options.append(f"{status_tag} {name}")
            items.append(key)
        return options, items

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown(self.title, classes="modal-markdown")
            if self.show_search:
                yield Input(placeholder=self.search_placeholder, id="modal-search-input")
            yield OptionList(*self.filtered_options, id="modal-option-list")
            yield Label("enter: connect • ctrl+d: disable/enable • esc: cancel • ↑/↓: navigate", id="modal-hint")

    def _on_key(self, event: events.Key) -> None:
        if event.key in ("ctrl+d", "ctrl_d"):
            opt_list = self.query_one("#modal-option-list", OptionList)
            idx = opt_list.highlighted
            if idx is not None and 0 <= idx < len(self.filtered_items):
                pkey = self.filtered_items[idx]
                if pkey:
                    if pkey in self.disabled_set:
                        self.disabled_set.remove(pkey)
                        if self.pm:
                            self.pm.set_provider_disabled(pkey, False)
                    else:
                        self.disabled_set.add(pkey)
                        if self.pm:
                            self.pm.set_provider_disabled(pkey, True)

                    options, items = self._build_options()
                    self.raw_options = options
                    self.raw_items = items
                    search_input = self.query_one("#modal-search-input", Input)
                    self.on_input_changed(Input.Changed(search_input, search_input.value))
                    opt_list.highlighted = idx
                    event.prevent_default()
                    event.stop()
                    return
        super()._on_key(event)


ConnectProviderScreen = ProvidersScreen


class ApiKeyInputScreen(ModalScreen[str | None]):
    """Modal API key input screen"""
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def action_quit_app(self) -> None:
        self.app.exit()

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

    def _on_key(self, event: events.Key) -> None:
        if event.key in ("shift+tab", "backtab", "shift_tab"):
            event.prevent_default()
            event.stop()
            return

    def action_cancel(self) -> None:
        self.dismiss(None)
