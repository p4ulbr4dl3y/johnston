"""Modal screen for managing workspace roots."""
from __future__ import annotations

import json
import os
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
from widgets.presentation.widgets.chat_input_paste import decode_pasted_path
from widgets.presentation.widgets.modal_header import ModalHeader
from widgets.presentation.widgets.modal_hint import ModalHint
from widgets.utils.key_aliases import expand_bindings
from widgets.utils.responsive import (
    MODAL_MEDIUM_MAX_WIDTH,
    MODAL_MIN_WIDTH,
    apply_modal_fit,
)
from widgets.utils.row_format import (
    MODAL_MEDIUM_ROW_WIDTH,
    format_badge_row,
    option_list_row_width,
)

__all__ = ["WorkspaceScreen", "WorkspaceInput", "WorkspaceOptionList", "get_root_scope"]


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


class WorkspaceInput(Input):
    """Input widget that forwards vertical navigation keys to OptionList and prevents select-all."""

    def _clear_selection(self) -> None:
        val_len = len(self.value)
        self.cursor_position = val_len
        try:
            from textual.widgets._input import Selection

            self.selection = Selection(val_len, val_len)
        except Exception:
            pass

    def _on_focus(self, event: events.Focus) -> None:
        super()._on_focus(event)
        self._clear_selection()
        self.call_after_refresh(self._clear_selection)

    async def _on_key(self, event: events.Key) -> None:
        key = (event.key or "").lower()

        if key in ("down", "key_down"):
            if self.screen and hasattr(self.screen, "focus_first_option"):
                getattr(self.screen, "focus_first_option")()
                event.stop()
                event.prevent_default()
                return

        elif key in ("up", "key_up"):
            if self.screen and hasattr(self.screen, "focus_last_option"):
                getattr(self.screen, "focus_last_option")()
                event.stop()
                event.prevent_default()
                return

        await super()._on_key(event)


class WorkspaceOptionList(HeaderWrapOptionList):
    """OptionList that routes boundary vertical navigation back to WorkspaceInput."""

    def action_cursor_down(self) -> None:
        if self.screen and hasattr(self.screen, "handle_option_list_down"):
            if getattr(self.screen, "handle_option_list_down")():
                return
        super().action_cursor_down()

    def action_cursor_up(self) -> None:
        if self.screen and hasattr(self.screen, "handle_option_list_up"):
            if getattr(self.screen, "handle_option_list_up")():
                return
        super().action_cursor_up()


class WorkspaceScreen(BaseModalScreen[None]):
    """Modal screen for viewing, adding, and removing workspace roots."""

    BINDINGS = expand_bindings([
        ("escape", "cancel", "Close"),
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
            yield WorkspaceInput(
                placeholder="Directory path (e.g. ~/projects/lib)...",
                id="workspace-add-input",
                classes="modal-input",
            )
            yield WorkspaceOptionList(id="workspace-option-list")
            yield ModalHint("enter Add • drop folder • esc Close", id=MODAL_HINT_ID)

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
            self.query_one("#workspace-add-input", WorkspaceInput).focus()
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

        active_tag = status_tag("ACTIVE")
        locked_tag = status_tag("LOCKED")
        for item in self.roots_data:
            path = item["path"]
            scope = item["scope"]
            stag = locked_tag if scope == "primary" else active_tag
            row = format_badge_row(path, badge=scope, target_width=target_w, prefix=f"{stag} ")
            opt_list.add_option(Option(row))
            self._option_actions.append(("root", item))

        if curr_idx is not None and curr_idx < len(opt_list._options):
            opt_list.highlighted = curr_idx
        elif len(self.roots_data) > 0:
            opt_list.highlighted = 0
        else:
            opt_list.highlighted = None

        self._update_hint()

    def _update_hint(self, idx: int | None = None) -> None:
        try:
            hint_widget = self.query_one(f"#{MODAL_HINT_ID}", ModalHint)
        except Exception:
            return

        try:
            inp = self.query_one("#workspace-add-input", WorkspaceInput)
            opt_list = self.query_one("#workspace-option-list", OptionList)
            if inp.has_focus and not opt_list.has_focus:
                hint_widget.update("enter Add • drop folder • esc Close")
                return
        except Exception:
            pass

        if idx is None:
            try:
                opt_list = self.query_one("#workspace-option-list", OptionList)
                idx = opt_list.highlighted
            except Exception:
                idx = None

        if idx is not None and 0 <= idx < len(self._option_actions):
            action_type, data = self._option_actions[idx]
            if action_type == "root" and data:
                if data.get("scope") == "primary":
                    hint_widget.update("drop folder • esc Close")
                    return
                hint_widget.update("d Delete • drop folder • esc Close")
                return

        hint_widget.update("enter Add • drop folder • esc Close")

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        self._update_hint()

    def focus_input(self) -> None:
        try:
            inp = self.query_one("#workspace-add-input", WorkspaceInput)
            inp.focus()
            self._update_hint()
        except Exception:
            pass

    def focus_first_option(self) -> None:
        try:
            opt_list = self.query_one("#workspace-option-list", OptionList)
            if len(opt_list._options) > 0:
                opt_list.highlighted = 0
                opt_list.focus()
                self._update_hint(0)
        except Exception:
            pass

    def focus_last_option(self) -> None:
        try:
            opt_list = self.query_one("#workspace-option-list", OptionList)
            if len(opt_list._options) > 0:
                opt_list.highlighted = len(opt_list._options) - 1
                opt_list.focus()
                self._update_hint(opt_list.highlighted)
        except Exception:
            pass

    def handle_option_list_down(self) -> bool:
        try:
            opt_list = self.query_one("#workspace-option-list", OptionList)
            if opt_list.highlighted is not None and opt_list.highlighted == len(opt_list._options) - 1:
                self.focus_input()
                return True
        except Exception:
            pass
        return False

    def handle_option_list_up(self) -> bool:
        try:
            opt_list = self.query_one("#workspace-option-list", OptionList)
            if opt_list.highlighted is not None and opt_list.highlighted == 0:
                self.focus_input()
                return True
        except Exception:
            pass
        return False

    def on_input_submitted(self, event: Input.Submitted) -> None:
        val = event.value.strip()
        if not val:
            if self.app and hasattr(self.app, "notify"):
                self.app.notify("Directory path required", severity="warning")
            return

        clean_path = decode_pasted_path(val.strip("'\""))
        abs_path = os.path.realpath(os.path.abspath(os.path.expanduser(clean_path)))
        if not os.path.isdir(abs_path):
            if self.app and hasattr(self.app, "notify"):
                self.app.notify(f"Directory '{clean_path}' does not exist", severity="error")
            return

        self.pm.add_workspace_root(abs_path)
        if self.app and hasattr(self.app, "notify"):
            self.app.notify(f"Added `{abs_path}` (session only)", severity="information")

        event.input.value = ""
        self.refresh_list()

    def on_paste(self, event: events.Paste) -> None:
        try:
            inp = self.query_one("#workspace-add-input", WorkspaceInput)
            if inp.has_focus:
                clean = decode_pasted_path(event.text)
                inp.insert_text_at_cursor(clean)
                event.stop()
                event.prevent_default()
                return
        except Exception:
            pass

        raw = event.text.strip()
        if not raw:
            return

        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        added_any = False
        for line in lines:
            clean_path = decode_pasted_path(line)
            abs_path = os.path.realpath(os.path.abspath(os.path.expanduser(clean_path)))
            if os.path.isdir(abs_path):
                event.stop()
                event.prevent_default()
                self.pm.add_workspace_root(abs_path)
                if self.app and hasattr(self.app, "notify"):
                    self.app.notify(f"Added `{abs_path}` (session only)", severity="information")
                added_any = True
            elif len(lines) == 1:
                if self.app and hasattr(self.app, "notify"):
                    self.app.notify(f"Path '{clean_path}' is not a directory", severity="warning")

        if added_any:
            self.refresh_list()

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self._update_hint(event.option_index)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        idx = event.option_index
        if idx is not None and 0 <= idx < len(self._option_actions):
            action_type, data = self._option_actions[idx]
            if action_type == "root" and data:
                if data.get("scope") == "primary":
                    if self.app and hasattr(self.app, "notify"):
                        self.app.notify("Primary workspace root cannot be removed", severity="warning")
                else:
                    self._confirm_and_remove(data["path"])

    def action_remove_root(self) -> None:
        try:
            inp = self.query_one("#workspace-add-input", WorkspaceInput)
            opt_list = self.query_one("#workspace-option-list", OptionList)
            if inp.has_focus and not opt_list.has_focus:
                return
        except Exception:
            pass

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
