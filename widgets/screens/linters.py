from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Markdown, OptionList

from core.linters_manager import get_linters_manager


class LintersScreen(ModalScreen[None]):
    """Modal screen for managing linters: enable/disable + details."""

    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("x", "details", "Details"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def action_quit_app(self) -> None:
        self.app.exit()

    def __init__(self):
        super().__init__()
        self.lm = get_linters_manager()
        self.linters: list[dict] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("### **Manage Linters**", classes="modal-markdown")
            yield OptionList(id="linters-option-list")
            yield Label("enter: toggle • x: details • esc: close", id="modal-hint")

    def on_mount(self) -> None:
        self.refresh_list()

    def refresh_list(self) -> None:
        self.linters = self.lm.load_linters()
        avail = self.lm.scan_available()
        opt_list = self.query_one("#linters-option-list", OptionList)
        prev_highlighted = opt_list.highlighted
        opt_list.clear_options()

        if not self.linters:
            opt_list.add_option("*No linters configured*")
            return

        for lint in self.linters:
            name = lint.get("name", "?")
            label = lint.get("label", name)
            enabled = bool(lint.get("enabled"))
            available = avail.get(name, False)
            install_hint = lint.get("install", "system")

            if available:
                status = r"[ON]" if enabled else r"[OFF]"
                extra = " — enabled" if enabled else " — disabled"
            else:
                status = r"[N/A]"
                extra = f" — not installed ({install_hint})"
            opt_list.add_option(f"{status} {label} · {install_hint}{extra}")

        opt_list.focus()
        if prev_highlighted is not None and 0 <= prev_highlighted < len(self.linters):
            opt_list.highlighted = prev_highlighted
        elif self.linters and opt_list.highlighted is None:
            opt_list.highlighted = 0

    def _current(self):
        opt_list = self.query_one("#linters-option-list", OptionList)
        idx = opt_list.highlighted
        if idx is not None and 0 <= idx < len(self.linters):
            return self.linters[idx]
        return None

    def action_cancel(self) -> None:
        if hasattr(self.app, "refresh_status_footer"):
            self.app.refresh_status_footer()
        self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.linters):
            target = self.linters[event.option_index]
            name = target.get("name")
            if not name:
                return
            new_state = not bool(target.get("enabled"))
            self.lm.set_enabled(name, new_state)
            self.refresh_list()
            opt_list = self.query_one("#linters-option-list", OptionList)
            opt_list.highlighted = event.option_index

    def action_details(self) -> None:
        target = self._current()
        if not target:
            return
        name = target.get("name", "?")
        label = target.get("label", name)
        install = target.get("install", "?")
        exts = ", ".join(target.get("extensions", [])) or "none"
        cmd = " ".join(target.get("cmd", []))
        self.app.notify(
            f"{label} [{install}] · files: {exts}\ncmd: {cmd}",
            title="Linter Details",
            severity="information",
            timeout=8,
        )
