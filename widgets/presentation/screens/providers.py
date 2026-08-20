from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Markdown, OptionList

from widgets.presentation.screens.base_modal import BaseModalScreen, status_tag
from widgets.presentation.screens.base_selection import BaseSelectionScreen
from widgets.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT_ID,
    MODAL_MARKDOWN,
    MODAL_MARKDOWN_CENTERED,
    MODAL_OPTION_LIST,
    MODAL_SEARCH_INPUT,
    SHIFT_TAB_KEYS,
)


class ProvidersScreen(BaseSelectionScreen[str]):
    """Modal provider selection screen for /providers command with MCP-style [] status tags"""

    def __init__(
        self, providers: dict, active_key: str, configured_keys: dict, disabled_providers: list = None, pm=None
    ):
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
            search_placeholder="Search providers...",
            hint_text="enter: connect • tab: toggle • ↑/↓: navigate • esc: cancel",
        )

    def _build_options(self):
        options = []
        items = []
        for pkey, p in self.providers.items():
            if not isinstance(p, dict):
                continue
            key = p.get("key") or pkey
            name = p.get("name") or pkey
            has_key = bool(self.configured_keys.get(key))
            is_active = key == self.active_key
            is_disabled = key in self.disabled_set or not p.get("enabled", True)

            if is_disabled:
                stag = status_tag("OFF")
            elif is_active:
                stag = status_tag("ACTIVE")
            elif has_key:
                stag = status_tag("ON")
            else:
                stag = status_tag("AUTH")

            options.append(f"{stag} {name}")
            items.append(key)
        return options, items

    BINDINGS = [
        ("tab", "toggle_disabled", "Toggle Disabled"),
        ("ctrl+t", "toggle_disabled", "Toggle Disabled"),
    ]

    def action_toggle_disabled(self) -> None:
        opt_list = self.query_one(MODAL_OPTION_LIST, OptionList)
        idx = opt_list.highlighted
        if idx is None and self.filtered_items:
            idx = 0
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
                search_input = self.query_one(MODAL_SEARCH_INPUT, Input)
                self.on_input_changed(Input.Changed(search_input, search_input.value))
                if self.filtered_items:
                    opt_list.highlighted = min(idx, len(self.filtered_items) - 1)

    def _on_key(self, event: events.Key) -> None:
        if event.key in ("tab", "ctrl+t", "ctrl_t", "ctrl+i"):
            self.action_toggle_disabled()
            event.prevent_default()
            event.stop()
            return
        super()._on_key(event)


class ApiKeyInputScreen(BaseModalScreen[str | None]):
    """Modal API key input screen"""

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

        with Vertical(id=MODAL_DIALOG_ID):
            yield Markdown(
                f"### **Connect {self.provider_name}**", classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}"
            )
            yield Markdown(f"Current API Key: `{masked}`", classes=MODAL_MARKDOWN)
            yield Input(placeholder="API Key...", value="", password=True, id="api-key-input")
            yield Label("enter: save • esc: cancel", id=MODAL_HINT_ID)

    def on_mount(self) -> None:
        self.query_one("#api-key-input", Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value.strip())

    def _on_key(self, event: events.Key) -> None:
        if event.key in SHIFT_TAB_KEYS:
            event.prevent_default()
            event.stop()
            return

    def action_cancel(self) -> None:
        self.dismiss(None)
