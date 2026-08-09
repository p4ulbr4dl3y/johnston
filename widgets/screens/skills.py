from typing import Any, Dict, Optional

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Markdown, OptionList

from core.config import CONFIG_DIR
from core.skill_manager import SkillManager
from widgets.screens.base_modal import BaseModalScreen, status_tag


class SkillDetailScreen(BaseModalScreen[bool]):
    """Modal screen displaying full details of a skill with option to activate"""

    BINDINGS = [
        ("escape", "cancel", "Back"),
        ("enter", "activate", "Activate"),
    ]

    def __init__(self, skill: Dict[str, Any]):
        super().__init__()
        self.skill = skill

    def compose(self) -> ComposeResult:
        scope_str = self.skill.get("scope", "global")
        header_md = f"### **Skill: {self.skill['name']}** (`{status_tag(scope_str)}`)"
        desc = self.skill.get("description", "").strip() or "No description provided."

        with Vertical(id="modal-dialog"):
            yield Markdown(header_md, classes="modal-markdown modal-markdown-centered")
            yield Markdown(desc, classes="modal-markdown")
            yield Label("enter: activate • esc: cancel", id="modal-hint")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_activate(self) -> None:
        self.dismiss(True)


class SkillsScreen(BaseModalScreen[Optional[Dict[str, Any]]]):
    """Modal screen for listing available skills (global and project) as one-liners"""

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("tab", "toggle_hidden", "Toggle Hidden"),
    ]

    def __init__(self):
        super().__init__()
        self.sm = SkillManager()
        self.skills: list[Dict[str, Any]] = []
        self.options: list[str] = []
        self.filtered_skills: list[Dict[str, Any]] = []
        self.filtered_options: list[str] = []
        self.search_query = ""
        self.load_skills()

    def load_skills(self) -> None:
        self.skills = self.sm.list_skills(include_hidden=True)
        self.options = []
        for s in self.skills:
            scope_t = status_tag(s["scope"])
            stat_t = status_tag("HIDDEN" if s.get("hidden") else "VISIBLE")
            self.options.append(f"{scope_t} {stat_t} {s['name']}")
        self.filtered_skills = list(self.skills)
        self.filtered_options = list(self.options)

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("### **Available Skills**", classes="modal-markdown modal-markdown-centered")
            yield Input(placeholder="Search skills...", id="modal-search-input")
            yield OptionList(id="skills-option-list")
            yield Label("enter: activate • tab: toggle status • esc: cancel", id="modal-hint")

    def on_mount(self) -> None:
        self.refresh_list(force_load=False)
        try:
            self.query_one("#modal-search-input", Input).focus()
        except Exception:
            pass

    def refresh_list(self, force_load: bool = True) -> None:
        if force_load:
            self.load_skills()
        self._apply_filter()

    def _apply_filter(self) -> None:
        q = self.search_query.strip().lower()
        if not q:
            self.filtered_skills = list(self.skills)
            self.filtered_options = list(self.options)
        else:
            self.filtered_skills = []
            self.filtered_options = []
            for s, opt in zip(self.skills, self.options):
                name = s.get("name", "").lower()
                desc = s.get("description", "").lower()
                scope = s.get("scope", "").lower()
                if q in name or q in desc or q in scope:
                    self.filtered_skills.append(s)
                    self.filtered_options.append(opt)

        try:
            opt_list = self.query_one("#skills-option-list", OptionList)
            opt_list.clear_options()
            if not self.filtered_skills:
                if not self.skills:
                    opt_list.add_option(f"*No skills found in {CONFIG_DIR}/skills/ or .johnston/skills/*")
                else:
                    opt_list.add_option("*No matching skills found*")
                return
            for opt in self.filtered_options:
                opt_list.add_option(opt)
            if self.filtered_skills:
                opt_list.highlighted = 0
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "modal-search-input":
            self.search_query = event.value
            self._apply_filter()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "modal-search-input":
            try:
                opt_list = self.query_one("#skills-option-list", OptionList)
                idx = opt_list.highlighted
                if idx is not None and 0 <= idx < len(self.filtered_skills):
                    self.dismiss(self.filtered_skills[idx])
                    return
            except Exception:
                pass
            self.dismiss(None)

    def _on_key(self, event: events.Key) -> None:
        if event.key in ("down", "up"):
            try:
                search_input = self.query_one("#modal-search-input", Input)
                if search_input.has_focus:
                    opt_list = self.query_one("#skills-option-list", OptionList)
                    if opt_list.highlighted is None and self.filtered_skills:
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

    def action_toggle_hidden(self) -> None:
        try:
            opt_list = self.query_one("#skills-option-list", OptionList)
            highlighted = opt_list.highlighted
            if highlighted is not None and 0 <= highlighted < len(self.filtered_skills):
                target = self.filtered_skills[highlighted]
                s_name = target["name"]
                self.sm.toggle_hidden(s_name)
                self.refresh_list()
                opt_list.highlighted = highlighted
        except Exception:
            pass

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.filtered_skills):
            self.dismiss(self.filtered_skills[event.option_index])
        else:
            self.dismiss(None)
