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
        ("h", "toggle_hidden", "Toggle Hidden"),
        ("tab", "toggle_hidden", "Toggle Hidden"),
        ("m", "toggle_hidden", "Toggle Hidden"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def action_quit_app(self) -> None:
        self.app.exit()

    def __init__(self):
        super().__init__()
        self.sm = SkillManager()
        self.skills: list[Dict[str, Any]] = []
        self.options: list[str] = []

    def load_skills(self) -> None:
        self.skills = self.sm.list_skills(include_hidden=True)
        self.options = []
        for s in self.skills:
            scope_tag = rf"\[{s['scope'].upper()}]"
            status_tag = r"\[HIDDEN]" if s.get("hidden") else r"\[VISIBLE]"
            self.options.append(f"{scope_tag} {status_tag} {s['name']}")

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("# Available Skills", classes="modal-markdown")
            yield OptionList(id="skills-option-list")
            yield Label("enter: activate • h/tab/m: toggle status • esc: cancel", id="modal-hint")

    def on_mount(self) -> None:
        self.refresh_list()

    def refresh_list(self) -> None:
        self.load_skills()
        try:
            opt_list = self.query_one("#skills-option-list", OptionList)
            opt_list.clear_options()
            if not self.skills:
                opt_list.add_option("*No skills found in ~/.johnston/skills/ or .johnston/skills/*")
                return
            for opt in self.options:
                opt_list.add_option(opt)
            opt_list.focus()
            if self.skills:
                opt_list.highlighted = 0
        except Exception:
            pass

    def action_toggle_hidden(self) -> None:
        try:
            opt_list = self.query_one("#skills-option-list", OptionList)
            highlighted = opt_list.highlighted
            if highlighted is not None and 0 <= highlighted < len(self.skills):
                target = self.skills[highlighted]
                s_name = target["name"]
                self.sm.toggle_hidden(s_name)
                self.refresh_list()
                opt_list.highlighted = highlighted
        except Exception:
            pass

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.skills):
            self.dismiss(self.skills[event.option_index])
        else:
            self.dismiss(None)
