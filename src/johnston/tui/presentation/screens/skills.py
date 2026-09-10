from typing import Any, Dict, Optional

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from johnston.core.dto import SkillDTO
from johnston.tui.presentation.screens.base_modal import BaseModalScreen, status_tag
from johnston.tui.presentation.screens.base_selection import HeaderWrapOptionList, ModalSearchNavMixin
from johnston.tui.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT,
    MODAL_HINT_ID,
    MODAL_SEARCH_INPUT,
    MODAL_SEARCH_INPUT_ID,
    TAB_KEYS,
)
from johnston.tui.presentation.widgets.footer_layout import get_theme_colors
from johnston.tui.presentation.widgets.modal_header import ModalHeader
from johnston.tui.presentation.widgets.modal_hint import ModalHint
from johnston.tui.utils.key_aliases import expand_bindings


class SkillsScreen(ModalSearchNavMixin, BaseModalScreen[Optional[Dict[str, Any]]]):
    """Modal screen for listing available skills (global and project) as one-liners"""

    search_nav_option_list_id = "skills-option-list"
    search_nav_filtered_attr = "filtered_skills"

    BINDINGS = expand_bindings([
        ("escape", "cancel", "Cancel"),
        ("tab", "toggle_hidden", "Toggle Hidden"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ])

    def __init__(self, client: Any = None):
        super().__init__()
        self._client = client
        self.skills: list[Any] = []
        self.options: list[str] = []
        self.filtered_skills: list = []
        self.filtered_options: list[str] = []
        self.search_query = ""
        self.load_skills()

    def _get_client(self) -> Any:
        if self._client is not None:
            return self._client
        try:
            app = self.app
            if hasattr(app, "client") and app.client is not None:
                return app.client
        except Exception:
            pass
        from johnston.core.client import JohnstonClient

        return JohnstonClient()

    def load_skills(self) -> None:
        client = self._get_client()
        if hasattr(client, "get_skills"):
            self.skills = client.get_skills()
        else:
            self.skills = []
        self.options = []
        for s in self.skills:
            is_hidden = not getattr(s, "enabled", True) if hasattr(s, "enabled") else getattr(s, "hidden", False)
            stat_t = status_tag("HIDDEN" if is_hidden else "VISIBLE")
            self.options.append(f"{stat_t} {getattr(s, 'name', '')}")
        self.filtered_skills = [
            s.to_dict()
            if hasattr(s, "to_dict")
            else {
                "name": getattr(s, "name", ""),
                "hidden": not getattr(s, "enabled", True) if hasattr(s, "enabled") else getattr(s, "hidden", False),
                "scope": getattr(s, "scope", "global"),
                "description": getattr(s, "description", ""),
                "path": getattr(s, "path", "") or getattr(s, "location", ""),
            }
            for s in self.skills
        ]
        self.filtered_options = list(self.options)

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID):
            yield ModalHeader("Available Skills", esc_hint="")
            yield Input(placeholder="Search...", id=MODAL_SEARCH_INPUT_ID, classes="modal-input")
            yield HeaderWrapOptionList(id="skills-option-list")
            total = len(self.skills)
            shown = sum(1 for s in self.filtered_skills if s is not None)
            yield ModalHint(
                "enter Select • tab Toggle • esc Close",
                right_text=f"{shown}/{total}" if total > 0 else "",
                id=MODAL_HINT_ID,
            )

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
        for scope in ("global", "project", "bundled"):
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
                _, _, t_muted, _ = get_theme_colors()
                opt_list.add_option(
                    Text("No skills found in ~/.johnston/skills/ or .johnston/skills/.", style=t_muted)
                )
            elif not any(s is not None for s in self.filtered_skills):
                opt_list.highlighted = None
            else:
                opt_list.add_options(self.filtered_options)
                # First selectable row
                for i, s in enumerate(self.filtered_skills):
                    if s is not None:
                        opt_list.highlighted = i
                        break

            from johnston.tui.utils.responsive import BREAKPOINT_HINT, resolve_screen_width

            is_compact = resolve_screen_width(self) < BREAKPOINT_HINT
            hint_lbl = self.query_one(MODAL_HINT, ModalHint)
            total = len(self.skills)
            shown = sum(1 for s in self.filtered_skills if s is not None)
            base_hint = "enter • tab • esc" if is_compact else "enter Select • tab Toggle • esc Close"
            hint_lbl.update(base_hint, right_text=f"{shown}/{total}" if total > 0 else "")
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
        client = self._get_client()
        try:
            now_hidden = client.toggle_skill(s_name)
        except Exception:
            # Disk state unchanged; keep showing the old tag.
            self.notify(f"Failed to toggle hidden for skill '{s_name}'", severity="error")
            return

        target["hidden"] = now_hidden
        stat_t = status_tag("HIDDEN" if now_hidden else "VISIBLE")
        new_opt = f"{stat_t} {s_name}"
        if highlighted < len(self.filtered_options):
            self.filtered_options[highlighted] = new_opt
        for i, s in enumerate(self.skills):
            if getattr(s, "name", "") == s_name:
                if isinstance(s, SkillDTO):
                    self.skills[i] = SkillDTO(
                        name=s.name,
                        description=s.description,
                        path=s.path,
                        enabled=not now_hidden,
                        is_project=s.is_project,
                        scope=s.scope,
                    )
                else:
                    setattr(s, "hidden", now_hidden)
                if i < len(self.options):
                    self.options[i] = new_opt
                break
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
