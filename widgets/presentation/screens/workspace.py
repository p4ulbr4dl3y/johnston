"""Modal screen for managing workspace roots."""
from __future__ import annotations

import json
import os
import shlex
from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from core.permission_manager import PermissionManager
from widgets.presentation.screens.base_modal import BaseModalScreen, status_tag
from widgets.presentation.screens.base_selection import HeaderWrapOptionList
from widgets.presentation.screens.confirm import ConfirmScreen
from widgets.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT_ID,
)
from widgets.presentation.widgets.modal_header import ModalHeader
from widgets.presentation.widgets.modal_hint import ModalHint
from widgets.utils.key_aliases import expand_bindings
from widgets.utils.responsive import (
    MODAL_COMPACT_MAX_WIDTH,
    MODAL_MEDIUM_MAX_WIDTH,
    MODAL_MIN_WIDTH,
    apply_modal_fit,
)
from widgets.utils.row_format import (
    MODAL_MEDIUM_ROW_WIDTH,
    format_badge_row,
    option_list_row_width,
)


def get_root_scope(pm: PermissionManager, path: str) -> str:
    """Determine the scope ('primary', 'project', 'local', or 'session') of a workspace root."""
    norm = os.path.realpath(os.path.abspath(path))
    primary = os.path.realpath(os.path.abspath(pm.current_project_dir or os.getcwd()))
    if norm == primary:
        return "primary"

    pdir = primary
    for cfg_file, scope in (("config.local.json", "local"), ("config.json", "project")):
        target = os.path.join(pdir, ".johnston", cfg_file)
        if os.path.isfile(target):
            try:
                with open(target, "r", encoding="utf-8") as f:
                    data = json.load(f)
                perms = data.get("permissions", {})
                roots = perms.get("writable_roots", [])
                if any(os.path.realpath(os.path.abspath(r)) == norm for r in roots if isinstance(r, str)):
                    return scope
            except Exception:
                pass
    return "session"


class AddWorkspaceRootScreen(BaseModalScreen[tuple[str, str] | None]):
    """Compact modal screen for entering a new workspace root path."""

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID, classes="modal-dialog-compact"):
            yield ModalHeader("Add Workspace Root", esc_hint="")
            yield Input(
                placeholder="Directory path (e.g. ~/projects/lib [--project])...",
                id="workspace-add-input",
                classes="modal-input",
            )
            yield ModalHint("enter Add • esc Cancel", id=MODAL_HINT_ID)

    def _apply_dialog_fit(self) -> None:
        try:
            dialog = self.query_one(f"#{MODAL_DIALOG_ID}")
            apply_modal_fit(
                dialog,
                MODAL_COMPACT_MAX_WIDTH,
                min_width=MODAL_MIN_WIDTH,
                max_width=MODAL_COMPACT_MAX_WIDTH,
            )
        except Exception:
            pass

    def on_mount(self) -> None:
        super().on_mount()
        self._apply_dialog_fit()
        try:
            inp = self.query_one("#workspace-add-input", Input)
            inp.focus()
        except Exception:
            pass

    def on_resize(self, event: events.Resize) -> None:
        self._apply_dialog_fit()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        val = event.value.strip()
        if not val:
            if self.app and hasattr(self.app, "notify"):
                self.app.notify("Directory path required", severity="warning")
            return

        try:
            tokens = shlex.split(val)
        except Exception:
            tokens = val.split()

        scope = "auto"
        path_tokens = []
        for token in tokens:
            if token in ("--local", "--project", "--session"):
                scope = token[2:]
            else:
                path_tokens.append(token)

        if not path_tokens:
            if self.app and hasattr(self.app, "notify"):
                self.app.notify("Directory path required", severity="warning")
            return

        raw_path = " ".join(path_tokens)
        abs_path = os.path.realpath(os.path.abspath(os.path.expanduser(raw_path)))
        if not os.path.isdir(abs_path):
            if self.app and hasattr(self.app, "notify"):
                self.app.notify(f"Directory '{raw_path}' does not exist", severity="error")
            return

        self.dismiss((abs_path, scope))


class WorkspaceScreen(BaseModalScreen[None]):
    """Modal screen for viewing, adding, and removing workspace roots."""

    BINDINGS = expand_bindings([
        ("escape", "cancel", "Close"),
        ("a", "add_root", "Add"),
        ("d", "remove_root", "Remove"),
        ("x", "remove_root", "Remove"),
        ("delete", "remove_root", "Remove"),
        ("backspace", "remove_root", "Remove"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ])

    def __init__(self, pm: PermissionManager | None = None) -> None:
        super().__init__()
        self.pm = pm or PermissionManager.get_instance()
        self.roots_data: list[dict[str, str]] = []
        self._option_actions: list[tuple[str, Any]] = []

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID, classes="modal-dialog-medium"):
            yield ModalHeader("Workspace Roots", esc_hint="")
            yield HeaderWrapOptionList(id="workspace-option-list")
            yield ModalHint("a Add • esc Close", id=MODAL_HINT_ID)

    def _apply_dialog_fit(self) -> None:
        try:
            dialog = self.query_one(f"#{MODAL_DIALOG_ID}")
            apply_modal_fit(
                dialog,
                MODAL_MEDIUM_MAX_WIDTH,
                min_width=MODAL_MIN_WIDTH,
                max_width=MODAL_MEDIUM_MAX_WIDTH,
            )
        except Exception:
            pass

    def on_mount(self) -> None:
        super().on_mount()
        self._apply_dialog_fit()
        self.refresh_list()
        try:
            self.query_one("#workspace-option-list", OptionList).focus()
        except Exception:
            pass

    def on_resize(self, event: events.Resize) -> None:
        self._apply_dialog_fit()
        self.refresh_list()

    def _load_roots(self) -> list[dict[str, str]]:
        all_roots = self.pm.get_workspace_roots()
        results = []
        for r in all_roots:
            scope = get_root_scope(self.pm, r)
            results.append({"path": r, "scope": scope})
        return results

    def refresh_list(self) -> None:
        self.roots_data = self._load_roots()
        self._option_actions = []
        try:
            opt_list = self.query_one("#workspace-option-list", OptionList)
        except Exception:
            return

        curr_idx = opt_list.highlighted
        opt_list.clear_options()

        target_w = option_list_row_width(opt_list, MODAL_MEDIUM_ROW_WIDTH)

        # 1. Existing roots
        active_tag = status_tag("ACTIVE")
        locked_tag = status_tag("LOCKED")
        for item in self.roots_data:
            path = item["path"]
            scope = item["scope"]
            stag = locked_tag if scope == "primary" else active_tag
            row = format_badge_row(path, badge=scope, target_width=target_w, prefix=f"{stag} ")
            opt_list.add_option(Option(row))
            self._option_actions.append(("root", item))

        # 2. Divider
        opt_list.add_option(Option("", disabled=True))
        self._option_actions.append(("sep", None))

        # 3. Add new root (prefix="+ " aligns '+' directly with '◆' / '●')
        add_label = format_badge_row("Add workspace root...", badge="", target_width=target_w, prefix="+ ")
        opt_list.add_option(Option(add_label))
        self._option_actions.append(("add", None))

        if curr_idx is not None and curr_idx < len(opt_list._options):
            opt_list.highlighted = curr_idx
        elif len(self.roots_data) > 0:
            opt_list.highlighted = 0
        else:
            opt_list.highlighted = len(opt_list._options) - 1

        self._update_hint(opt_list.highlighted)

    def _update_hint(self, idx: int | None = None) -> None:
        try:
            hint_widget = self.query_one(f"#{MODAL_HINT_ID}", ModalHint)
        except Exception:
            return

        if idx is None:
            try:
                opt_list = self.query_one("#workspace-option-list", OptionList)
                idx = opt_list.highlighted
            except Exception:
                idx = None

        if idx is not None and 0 <= idx < len(self._option_actions):
            action_type, data = self._option_actions[idx]
            if action_type == "add":
                hint_widget.update("enter Add • esc Close")
                return
            if action_type == "root" and data:
                if data.get("scope") == "primary":
                    hint_widget.update("a Add • esc Close")
                    return
                hint_widget.update("d Delete • a Add • esc Close")
                return

        hint_widget.update("a Add • esc Close")

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self._update_hint(event.option_index)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        idx = event.option_index
        if idx is not None and 0 <= idx < len(self._option_actions):
            action_type, data = self._option_actions[idx]
            if action_type == "add":
                self.action_add_root()
            elif action_type == "root" and data:
                if data.get("scope") == "primary":
                    if self.app and hasattr(self.app, "notify"):
                        self.app.notify("Primary workspace root cannot be removed", severity="warning")
                else:
                    self._confirm_and_remove(data["path"])

    def action_add_root(self) -> None:
        def on_added(result: tuple[str, str] | None) -> None:
            if result:
                path, scope = result
                used_scope = self.pm.save_workspace_root(path, scope=scope)
                scope_desc = {
                    "session": "session only",
                    "local": "local config",
                    "project": "project config",
                }.get(used_scope, used_scope)
                if self.app and hasattr(self.app, "notify"):
                    self.app.notify(f"Added `{path}` ({scope_desc})", severity="information")
                self.refresh_list()
            try:
                self.query_one("#workspace-option-list", OptionList).focus()
            except Exception:
                pass

        if self.app and hasattr(self.app, "push_screen"):
            self.app.push_screen(AddWorkspaceRootScreen(), callback=on_added)

    def action_remove_root(self) -> None:
        try:
            opt_list = self.query_one("#workspace-option-list", OptionList)
            idx = opt_list.highlighted
        except Exception:
            return

        if idx is not None and 0 <= idx < len(self._option_actions):
            action_type, data = self._option_actions[idx]
            if action_type == "root" and data:
                if data.get("scope") == "primary":
                    if self.app and hasattr(self.app, "notify"):
                        self.app.notify("Primary workspace root cannot be removed", severity="warning")
                    return
                self._confirm_and_remove(data["path"])

    def _confirm_and_remove(self, path: str) -> None:
        def on_confirmed(confirmed: bool) -> None:
            if confirmed:
                self.pm.remove_persisted_workspace_root(path)
                if self.app and hasattr(self.app, "notify"):
                    self.app.notify(f"Removed `{path}` from workspace roots", severity="information")
                self.refresh_list()
            try:
                self.query_one("#workspace-option-list", OptionList).focus()
            except Exception:
                pass

        if self.app and hasattr(self.app, "push_screen"):
            self.app.push_screen(
                ConfirmScreen(
                    title="### **Delete Workspace Root**",
                    message=f"Delete **{path}**?\nThis cannot be undone.",
                    confirm_label="delete",
                    cancel_label="cancel",
                ),
                callback=on_confirmed,
            )
        else:
            self.pm.remove_persisted_workspace_root(path)
            self.refresh_list()
