from typing import Any, Dict, Optional

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Markdown, OptionList
from textual.widgets.option_list import Option

from core.application.skills.manager import SkillManager
from core.domain.defaults.config import THEME_MUTED
from core.infrastructure.platform.paths import CONFIG_DIR
from widgets.presentation.screens.base_modal import BaseModalScreen, status_tag
from widgets.presentation.screens.base_selection import HeaderWrapOptionList, ModalSearchNavMixin
from widgets.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT_ID,
    MODAL_MARKDOWN,
    MODAL_MARKDOWN_CENTERED,
    MODAL_SEARCH_INPUT,
    MODAL_SEARCH_INPUT_ID,
)


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

        with Vertical(id=MODAL_DIALOG_ID):
            yield Markdown(header_md, classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}")
            yield Markdown(desc, classes=MODAL_MARKDOWN)
            yield Label("enter: activate • esc: cancel", id=MODAL_HINT_ID)

    def action_cancel(self) -> None:
        self.dismiss(False)

    def action_activate(self) -> None:
        self.dismiss(True)


class SkillsScreen(ModalSearchNavMixin, BaseModalScreen[Optional[Dict[str, Any]]]):
    """Modal screen for listing available skills (global and project) as one-liners"""

    search_nav_option_list_id = "skills-option-list"
    search_nav_filtered_attr = "filtered_skills"

    BINDINGS = [
        ("escape", "cancel", "Cancel"),
        ("tab", "toggle_hidden", "Toggle Hidden"),
    ]

    def __init__(self):
        super().__init__()
        self.sm = SkillManager()
        self.skills = []
        self.options: list[str] = []
        self.filtered_skills: list = []
        self.filtered_options: list[str] = []
        self.search_query = ""
        self.load_skills()

    def load_skills(self) -> None:
        self.skills = self.sm.list_skills(include_hidden=True)
        self.options = []
        for s in self.skills:
            stat_t = status_tag("HIDDEN" if s.hidden else "VISIBLE")
            self.options.append(f"   {stat_t} {s.name}")
        self.filtered_skills = [s.to_dict() for s in self.skills]
        self.filtered_options = list(self.options)

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID):
            yield Markdown("### **Available Skills**", classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}")
            yield Input(placeholder="Search skills...", id=MODAL_SEARCH_INPUT_ID)
            yield HeaderWrapOptionList(id="skills-option-list")
            yield Label("enter: activate • tab: toggle hidden • esc: cancel", id=MODAL_HINT_ID)

    def on_mount(self) -> None:
        self.refresh_list(force_load=False)
        try:
            self.query_one(MODAL_SEARCH_INPUT, Input).focus()
        except Exception:
            pass

    def refresh_list(self, force_load: bool = True) -> None:
        if force_load:
            self.load_skills()
        self._apply_filter()

    def _apply_filter(self) -> None:
        q = self.search_query.strip().lower()

        # Build grouped (global/project) filtered entries: None marks a header
        # row, a Dict marks a real skill (mirrors BaseSelectionScreen sectioning).
        self.filtered_skills = []
        self.filtered_options = []
        first_group = True
        for scope in ("global", "project"):
            group = []
            for s, opt in zip(self.skills, self.options):
                if s.scope.value != scope:
                    continue
                if not q or q in s.name.lower() or q in s.description.lower() or q in scope:
                    group.append((s, opt))
            if not group:
                continue
            if not first_group:
                self.filtered_skills.append(None)
                self.filtered_options.append(Option("", disabled=True))
            first_group = False
            self.filtered_skills.append(None)
            self.filtered_options.append(Option(scope.capitalize(), disabled=True))
            for s, opt in group:
                self.filtered_skills.append(s.to_dict())
                self.filtered_options.append(opt)

        try:
            opt_list = self.query_one("#skills-option-list", OptionList)
            opt_list.clear_options()
            if not self.skills:
                opt_list.add_option(
                    Text(f"No skills found in {CONFIG_DIR}/skills/ or .johnston/skills/.", style=THEME_MUTED)
                )
                return
            if not any(s is not None for s in self.filtered_skills):
                opt_list.highlighted = None
                return
            opt_list.add_options(self.filtered_options)
            # First selectable row
            for i, s in enumerate(self.filtered_skills):
                if s is not None:
                    opt_list.highlighted = i
                    break
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == MODAL_SEARCH_INPUT_ID:
            self.search_query = event.value
            self._apply_filter()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == MODAL_SEARCH_INPUT_ID:
            try:
                opt_list = self.query_one("#skills-option-list", OptionList)
                idx = opt_list.highlighted
                target = self.filtered_skills[idx] if idx is not None and 0 <= idx < len(self.filtered_skills) else None
                if target is not None:
                    self.dismiss(target)
                    return
            except Exception:
                pass
            self.dismiss(None)

    def _on_key(self, event: events.Key) -> None:
        self._handle_search_navigation(event)

    def action_toggle_hidden(self) -> None:
        try:
            opt_list = self.query_one("#skills-option-list", OptionList)
            highlighted = opt_list.highlighted
            target = self.filtered_skills[highlighted] if highlighted is not None and 0 <= highlighted < len(self.filtered_skills) else None
            if target is None:
                return
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
            target = self.filtered_skills[event.option_index]
            if target is not None:
                self.dismiss(target)
                return
        self.dismiss(None)
