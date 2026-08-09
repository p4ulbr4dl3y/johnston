from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Markdown, OptionList

from core.linters_manager import get_linters_manager
from widgets.screens.base_modal import BaseModalScreen, status_tag


class LintersScreen(BaseModalScreen[None]):
    """Modal screen for managing linters: enable/disable."""

    BINDINGS = [
        ("escape", "cancel", "Close"),
    ]

    def __init__(self):
        super().__init__()
        self.lm = get_linters_manager()
        self.linters: list[dict] = []
        self.filtered_linters: list[dict] = []
        self.search_query = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("### **Manage Linters**", classes="modal-markdown modal-markdown-centered")
            yield Input(placeholder="Search linters...", id="modal-search-input")
            yield OptionList(id="linters-option-list")
            yield Label("enter: toggle • esc: cancel", id="modal-hint")

    def on_mount(self) -> None:
        self.refresh_list()
        try:
            self.query_one("#modal-search-input", Input).focus()
        except Exception:
            pass

    def refresh_list(self) -> None:
        self.linters = self.lm.load_linters()
        avail = self.lm.scan_available()
        opt_list = self.query_one("#linters-option-list", OptionList)
        prev_highlighted = opt_list.highlighted
        opt_list.clear_options()

        if not self.linters:
            opt_list.add_option("*No linters configured*")
            self.filtered_linters = []
            return

        q = self.search_query.strip().lower()
        if not q:
            self.filtered_linters = list(self.linters)
        else:
            self.filtered_linters = [
                lint for lint in self.linters
                if q in lint.get("name", "").lower()
                or q in lint.get("label", "").lower()
                or any(q in ext.lower() for ext in lint.get("extensions", []))
            ]

        if not self.filtered_linters:
            opt_list.add_option("*No matching linters found*")
            return

        for lint in self.filtered_linters:
            name = lint.get("name", "?")
            label = lint.get("label", name)
            enabled = bool(lint.get("enabled"))
            available = avail.get(name, False)

            if available:
                status = status_tag("ON" if enabled else "OFF")
                extra = " — enabled" if enabled else " — disabled"
            else:
                status = status_tag("N/A")
                extra = " — not installed"
            opt_list.add_option(f"{status} {label}{extra}")

        if prev_highlighted is not None and 0 <= prev_highlighted < len(self.filtered_linters):
            opt_list.highlighted = prev_highlighted
        elif self.filtered_linters and opt_list.highlighted is None:
            opt_list.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "modal-search-input":
            self.search_query = event.value
            self.refresh_list()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "modal-search-input":
            opt_list = self.query_one("#linters-option-list", OptionList)
            idx = opt_list.highlighted
            if idx is not None and 0 <= idx < len(self.filtered_linters):
                target = self.filtered_linters[idx]
                name = target.get("name")
                if not name:
                    return
                new_state = not bool(target.get("enabled"))
                self.lm.set_enabled(name, new_state)
                self.refresh_list()
                opt_list.highlighted = idx

    def _on_key(self, event: events.Key) -> None:
        if event.key in ("down", "up"):
            try:
                search_input = self.query_one("#modal-search-input", Input)
                if search_input.has_focus:
                    opt_list = self.query_one("#linters-option-list", OptionList)
                    if opt_list.highlighted is None and self.filtered_linters:
                        opt_list.highlighted = 0
                    elif opt_list.highlighted is not None:
                        if event.key == "down":
                            opt_list.action_cursor_down()
                        else:
                            opt_list.action_cursor_up()
                    event.prevent_default()
                    event.stop()
            except Exception:
                pass

    def action_cancel(self) -> None:
        if hasattr(self.app, "refresh_status_footer"):
            self.app.refresh_status_footer()
        self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.filtered_linters):
            target = self.filtered_linters[event.option_index]
            name = target.get("name")
            if not name:
                return
            new_state = not bool(target.get("enabled"))
            self.lm.set_enabled(name, new_state)
            self.refresh_list()
            opt_list = self.query_one("#linters-option-list", OptionList)
            opt_list.highlighted = event.option_index

