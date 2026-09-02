from typing import Any, Dict, Optional

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from core.application.skills.manager import get_skill_manager
from core.domain.defaults.config import THEME_MUTED
from core.infrastructure.platform.paths import CONFIG_DIR
from widgets.presentation.screens.base_modal import BaseModalScreen, status_tag
from widgets.presentation.screens.base_selection import HeaderWrapOptionList, ModalSearchNavMixin
from widgets.presentation.screens.constants import (
    ESC_HINT_CLOSE,
    MODAL_DIALOG_ID,
    MODAL_HINT,
    MODAL_HINT_ID,
    MODAL_SEARCH_INPUT,
    MODAL_SEARCH_INPUT_ID,
    TAB_KEYS,
)
from widgets.presentation.widgets.modal_header import ModalHeader
from widgets.presentation.widgets.modal_hint import ModalHint
from widgets.utils.key_aliases import expand_bindings


class SkillsScreen(ModalSearchNavMixin, BaseModalScreen[Optional[Dict[str, Any]]]):
    """Modal screen for listing available skills (global and project) as one-liners"""

    search_nav_option_list_id = "skills-option-list"
    search_nav_filtered_attr = "filtered_skills"

    space_actions = ("toggle_hidden",)

    BINDINGS = expand_bindings([
        ("escape", "cancel", "Cancel"),
        ("tab", "toggle_hidden", "Toggle Hidden"),
        ("space", "toggle_hidden", "Toggle Hidden"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ])

    def __init__(self):
        super().__init__()
        self.sm = get_skill_manager()
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
            stat_t = status_tag("HIDDEN" if getattr(s, "hidden", False) else "VISIBLE")
            self.options.append(f"{stat_t} {getattr(s, 'name', '')}")
        self.filtered_skills = [
            s.to_dict() if hasattr(s, "to_dict") else {"name": getattr(s, "name", ""), "hidden": getattr(s, "hidden", False)}
            for s in self.skills
        ]
        self.filtered_options = list(self.options)

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID):
            yield ModalHeader("Available Skills", esc_hint="")
            yield Input(placeholder="Search...", id=MODAL_SEARCH_INPUT_ID, classes="modal-input")
            yield HeaderWrapOptionList(id="skills-option-list")
            yield ModalHint(f"enter: select • space: toggle • {ESC_HINT_CLOSE}", id=MODAL_HINT_ID)

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
                s_scope = getattr(s, "scope", None)
                s_scope_val = s_scope.value if hasattr(s_scope, "value") else str(s_scope or "global").lower()
                if s_scope_val != scope:
                    continue
                s_name = getattr(s, "name", "")
                s_desc = getattr(s, "description", "")
                if not q or q in s_name.lower() or q in s_desc.lower() or q in scope:
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
                s_dict = (
                    s.to_dict()
                    if hasattr(s, "to_dict")
                    else {"name": getattr(s, "name", ""), "hidden": getattr(s, "hidden", False)}
                )
                self.filtered_skills.append(s_dict)
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

            from widgets.utils.responsive import BREAKPOINT_HINT, resolve_screen_width

            is_compact = resolve_screen_width(self) < BREAKPOINT_HINT
            hint_lbl = self.query_one(MODAL_HINT, Label)
            hint_lbl.update("enter • space • esc" if is_compact else f"enter: select • space: toggle • {ESC_HINT_CLOSE}")
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
        if event.key in TAB_KEYS:
            self.action_toggle_hidden()
            event.prevent_default()
            event.stop()
            return
        # `space` is a real binding now (see space_actions/check_action), so it
        # is advertised in the hint and /help instead of being invisible.
        self._handle_search_navigation(event)

    def action_toggle_hidden(self) -> None:
        try:
            opt_list = self.query_one("#skills-option-list", OptionList)
            highlighted = opt_list.highlighted
            target = self.filtered_skills[highlighted] if highlighted is not None and 0 <= highlighted < len(self.filtered_skills) else None
        except Exception:
            return
        if target is None:
            return

        s_name = target["name"]
        try:
            now_hidden = self.sm.toggle_hidden(s_name)
        except Exception:
            # Disk state unchanged; keep showing the old tag.
            self.notify(f"Failed to toggle hidden for skill '{s_name}'", severity="error")
            return

        target["hidden"] = now_hidden
        stat_t = status_tag("HIDDEN" if now_hidden else "VISIBLE")
        new_opt = f"{stat_t} {s_name}"
        if highlighted < len(self.filtered_options):
            self.filtered_options[highlighted] = new_opt
        try:
            opt_list.replace_option_prompt_at_index(highlighted, new_opt)
        except Exception:
            self.refresh_list()
            opt_list.highlighted = highlighted

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.filtered_skills):
            target = self.filtered_skills[event.option_index]
            if target is not None:
                self.dismiss(target)
                return
        self.dismiss(None)
