from typing import Any, Dict, Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Markdown, OptionList

from core.skill_manager import SkillManager


class SkillsScreen(ModalScreen[Optional[Dict[str, Any]]]):
    """Модальное окно списка доступных скиллов (глобальных и проектных)"""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self):
        super().__init__()
        self.sm = SkillManager()
        self.skills = self.sm.list_skills()
        self.options = []
        for s in self.skills:
            scope_tag = rf"\[{s['scope'].upper()}]"
            desc = f" — {s['description']}" if s['description'] else ""
            self.options.append(f"{scope_tag} {s['name']}{desc}")

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("# Available Skills", classes="modal-markdown")
            if self.options:
                yield OptionList(*self.options)
            else:
                yield Markdown("*No skills found in ~/.johnston/skills/ or .johnston/skills/*", classes="modal-body")

    def on_mount(self) -> None:
        if self.options:
            self.query_one(OptionList).focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.skills):
            self.dismiss(self.skills[event.option_index])
        else:
            self.dismiss(None)
