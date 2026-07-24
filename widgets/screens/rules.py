from typing import List

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Markdown, OptionList

from core.rules_manager import RuleDefinition, RulesManager


class RulesScreen(ModalScreen[None]):
    """Modal screen for viewing active Markdown rules (/rules command)"""

    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "cancel", "Close"),
    ]

    def __init__(self):
        super().__init__()
        self.rm = RulesManager.get_instance()
        self.rules: List[RuleDefinition] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("# User & Project Rules", classes="modal-markdown")
            yield OptionList(id="rules-option-list")
            yield Label("esc: close • ↑/↓: navigate", id="modal-hint")

    def on_mount(self) -> None:
        self.refresh_list()
        opt_list = self.query_one("#rules-option-list", OptionList)
        if self.rules:
            opt_list.highlighted = 0

    def refresh_list(self) -> None:
        self.rules = self.rm.load_rules()
        opt_list = self.query_one("#rules-option-list", OptionList)
        opt_list.clear_options()

        if not self.rules:
            opt_list.add_option("*No rules configured in ~/.johnston/rules or .johnston/rules*")
            return

        for r in self.rules:
            source_tag = rf"\[{r.source.upper()}]"
            mode_str = "/".join(m.upper() for m in r.modes) if r.modes else "ALL"
            mode_tag = rf"\[{mode_str}]"

            desc = r.description
            if not desc and r.content:
                first_line = r.content.splitlines()[0].strip("#* ").strip()
                desc = first_line[:60] if first_line else ""

            desc_info = f" — {desc}" if desc else ""
            opt_list.add_option(f"{source_tag} {mode_tag} {r.name}{desc_info}")

        opt_list.focus()

    def action_cancel(self) -> None:
        self.dismiss(None)
