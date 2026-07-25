from typing import Any, Dict, Optional

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Markdown, OptionList

from core.skill_manager import SkillManager


class SkillDetailScreen(ModalScreen[bool]):
    """Modal screen displaying full details of a skill with option to activate"""
    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "cancel", "Back"),
        ("enter", "activate", "Activate"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def action_quit_app(self) -> None:
        self.app.exit()

    def __init__(self, skill: Dict[str, Any]):
        super().__init__()
        self.skill = skill

    def compose(self) -> ComposeResult:
        scope_tag = self.skill.get("scope", "global").upper()
        header_md = f"### **Skill: {self.skill['name']}** (`[{scope_tag}]`)"
        desc = self.skill.get("description", "").strip() or "No description provided."
        body_md = f"{header_md}\n\n---\n\n{desc}"

        with Vertical(id="modal-dialog"):
            yield Markdown(body_md, classes="modal-markdown")
            yield Label("enter: activate • esc: back", id="modal-hint")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_activate(self) -> None:
        self.dismiss(True)


class SkillsScreen(ModalScreen[Optional[Dict[str, Any]]]):
    """Modal screen for listing available skills (global and project) as one-liners"""

    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def action_quit_app(self) -> None:
        self.app.exit()

    def __init__(self):
        super().__init__()
        self.sm = SkillManager()
        self.skills = self.sm.list_skills()
        self.options = []
        for s in self.skills:
            scope_tag = rf"\[{s['scope'].upper()}]"
            self.options.append(f"{scope_tag} {s['name']}")

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("# Available Skills", classes="modal-markdown")
            if self.options:
                yield OptionList(*self.options)
            else:
                yield Markdown("*No skills found in ~/.johnston/skills/ or .johnston/skills/*", classes="modal-body")
            yield Label("enter: view detail • esc: cancel • ↑/↓: navigate", id="modal-hint")

    def on_mount(self) -> None:
        if self.options:
            opt_list = self.query_one(OptionList)
            opt_list.focus()
            opt_list.highlighted = 0

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.skills):
            target_skill = self.skills[event.option_index]

            def on_detail_close(activate: bool | None) -> None:
                if activate:
                    self.dismiss(target_skill)
                else:
                    opt_list = self.query_one(OptionList)
                    opt_list.focus()
                    opt_list.highlighted = event.option_index

            self.app.push_screen(SkillDetailScreen(target_skill), callback=on_detail_close)
        else:
            self.dismiss(None)
