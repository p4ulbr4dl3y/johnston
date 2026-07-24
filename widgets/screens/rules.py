from typing import List

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Markdown, OptionList

from core.rules_manager import RuleDefinition, RulesManager


class RuleDetailScreen(ModalScreen[None]):
    """Modal screen displaying full markdown content of a rule"""
    BINDINGS = [("escape", "cancel", "Back")]

    def __init__(self, rule: RuleDefinition):
        super().__init__()
        self.rule = rule

    def compose(self) -> ComposeResult:
        source_tag = self.rule.source.upper()
        mode_str = "/".join(m.upper() for m in self.rule.modes) if self.rule.modes else "ALL"

        header_md = f"### **Rule: {self.rule.name}** (`[{source_tag}] [{mode_str}]`)\n\n"
        if self.rule.description:
            header_md += f"**Description:** *{self.rule.description}*\n\n"
        if self.rule.globs:
            globs_str = ", ".join(f"`{g}`" for g in self.rule.globs)
            header_md += f"**Globs:** {globs_str}\n\n"

        body_md = f"{header_md}---\n\n{self.rule.content}"

        with Vertical(id="modal-dialog"):
            yield Markdown(body_md, classes="modal-markdown")
            yield Label("esc: back", id="modal-hint")

    def action_cancel(self) -> None:
        self.dismiss(None)


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
            yield Label("enter: view detail • esc: close • ↑/↓: navigate", id="modal-hint")

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
            opt_list.add_option(f"{source_tag} {mode_tag} {r.name}")

        opt_list.focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.rules):
            target_rule = self.rules[event.option_index]

            def on_detail_close(_: None) -> None:
                opt_list = self.query_one("#rules-option-list", OptionList)
                opt_list.focus()
                opt_list.highlighted = event.option_index

            self.app.push_screen(RuleDetailScreen(target_rule), callback=on_detail_close)
