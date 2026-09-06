"""Modal screen for managing workspace roots."""
from __future__ import annotations

import json
import os
import shlex
from pathlib import Path
from typing import Any, Iterable

from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import DirectoryTree, Input, OptionList, Static
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
    BREAKPOINT_COMPACT,
    MODAL_COMPACT_MAX_WIDTH,
    MODAL_MIN_WIDTH,
    MODAL_WIDE_MAX_WIDTH,
    apply_modal_fit,
    is_compact_width,
    resolve_width,
)
from widgets.utils.row_format import (
    MODAL_MEDIUM_ROW_WIDTH,
    WORKSPACE_SIDEBAR_ROW_WIDTH,
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

    def on_paste(self, event: events.Paste) -> None:
        clean = decode_pasted_path(event.text)
        try:
            inp = self.query_one("#workspace-add-input", Input)
            inp.insert_text_at_cursor(clean)
            event.stop()
            event.prevent_default()
        except Exception:
            pass

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
        clean_path = decode_pasted_path(raw_path)
        abs_path = os.path.realpath(os.path.abspath(clean_path))
        if not os.path.isdir(abs_path):
            if self.app and hasattr(self.app, "notify"):
                self.app.notify(f"Directory '{clean_path}' does not exist", severity="error")
            return

        self.dismiss((abs_path, scope))


class WorkspaceDirectoryTree(DirectoryTree):
    """Directory tree filtered for workspace browsing (skips VCS, caches, venvs)."""

    IGNORED_NAMES = {
        ".git",
        ".hg",
        ".svn",
        ".venv",
        "venv",
        "env",
        ".env",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".ruff_cache",
        ".mypy_cache",
        ".tox",
        ".idea",
        ".vscode",
        "dist",
        "build",
        ".DS_Store",
    }

    def __init__(self, path: str | Path, **kwargs: Any) -> None:
        super().__init__(path, **kwargs)
        self.show_root = False
        self.guide_depth = 2

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return [p for p in paths if p.name not in self.IGNORED_NAMES]


class WorkspaceScreen(BaseModalScreen[None]):
    """Modal screen for viewing, adding, and removing workspace roots."""

    BINDINGS = expand_bindings([
        ("escape", "cancel", "Close"),
        ("tab", "toggle_pane", "Switch"),
        ("shift+tab", "toggle_pane", "Switch"),
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
        with Vertical(id=MODAL_DIALOG_ID, classes="modal-dialog-wide"):
            yield ModalHeader("Workspace Roots", esc_hint="")
            with Horizontal(id="workspace-split-container"):
                with Vertical(id="workspace-left-pane"):
                    yield HeaderWrapOptionList(id="workspace-option-list")
                with Vertical(id="workspace-right-pane"):
                    yield Static(id="workspace-tree-header")
                    initial_root = self.pm.current_project_dir or os.getcwd()
                    yield WorkspaceDirectoryTree(Path(initial_root), id="workspace-dir-tree")
                    yield Static(id="workspace-info-view")
            yield ModalHint("tab Tree • a Add • esc Close", id=MODAL_HINT_ID)

    def _update_layout(self) -> None:
        width = resolve_width(self)
        is_compact = is_compact_width(width, breakpoint=BREAKPOINT_COMPACT)
        try:
            left_pane = self.query_one("#workspace-left-pane", Vertical)
            right_pane = self.query_one("#workspace-right-pane", Vertical)
        except Exception:
            return

        if is_compact:
            left_pane.add_class("-full-width")
            right_pane.add_class("-hidden")
            try:
                tree = self.query_one("#workspace-dir-tree", WorkspaceDirectoryTree)
                if self.focused == tree:
                    self.query_one("#workspace-option-list", OptionList).focus()
            except Exception:
                pass
        else:
            left_pane.remove_class("-full-width")
            right_pane.remove_class("-hidden")

    def _apply_dialog_fit(self) -> None:
        try:
            dialog = self.query_one(f"#{MODAL_DIALOG_ID}")
            apply_modal_fit(
                dialog,
                MODAL_WIDE_MAX_WIDTH,
                min_width=MODAL_MIN_WIDTH,
                max_width=MODAL_WIDE_MAX_WIDTH,
            )
        except Exception:
            pass

    def on_mount(self) -> None:
        super().on_mount()
        self._update_layout()
        self._apply_dialog_fit()
        self.refresh_list()
        try:
            self.query_one("#workspace-option-list", OptionList).focus()
        except Exception:
            pass

    def on_resize(self, event: events.Resize) -> None:
        self._update_layout()
        self._apply_dialog_fit()
        self.refresh_list()

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        self._update_hint()

    def on_key(self, event: events.Key) -> None:
        if event.key == "right":
            try:
                opt_list = self.query_one("#workspace-option-list", OptionList)
                right_pane = self.query_one("#workspace-right-pane", Vertical)
                if self.focused == opt_list and not right_pane.has_class("-hidden"):
                    tree = self.query_one("#workspace-dir-tree", WorkspaceDirectoryTree)
                    if not tree.has_class("-hidden"):
                        tree.focus()
                        event.stop()
                        event.prevent_default()
            except Exception:
                pass

    def on_directory_tree_directory_selected(self, event: DirectoryTree.DirectorySelected) -> None:
        event.stop()

    def on_directory_tree_file_selected(self, event: DirectoryTree.FileSelected) -> None:
        event.stop()

    def action_toggle_pane(self) -> None:
        try:
            right_pane = self.query_one("#workspace-right-pane", Vertical)
            if right_pane.has_class("-hidden"):
                return
            tree = self.query_one("#workspace-dir-tree", WorkspaceDirectoryTree)
            opt_list = self.query_one("#workspace-option-list", OptionList)
            if self.focused == tree:
                opt_list.focus()
            else:
                if not tree.has_class("-hidden"):
                    tree.focus()
                else:
                    opt_list.focus()
            self._update_hint()
        except Exception:
            pass

    def _load_roots(self) -> list[dict[str, str]]:
        all_roots = self.pm.get_workspace_roots()
        results = []
        for r in all_roots:
            scope = get_root_scope(self.pm, r)
            results.append({"path": r, "scope": scope})
        return results

    def _update_tree_for_option(self, idx: int | None) -> None:
        try:
            tree = self.query_one("#workspace-dir-tree", WorkspaceDirectoryTree)
            header = self.query_one("#workspace-tree-header", Static)
            info = self.query_one("#workspace-info-view", Static)
        except Exception:
            return

        if idx is None or not (0 <= idx < len(self._option_actions)):
            return

        action_type, data = self._option_actions[idx]
        if action_type == "root" and data:
            path = data.get("path", "")
            base = os.path.basename(path) or path
            header.update(f"[bold]{base}[/] [dim]({path})[/]")
            if os.path.isdir(path):
                tree.remove_class("-hidden")
                info.add_class("-hidden")
                path_obj = Path(path)
                if tree.path != path_obj:
                    tree.path = path_obj
            else:
                tree.add_class("-hidden")
                info.remove_class("-hidden")
                info.update(f"[yellow]Directory not found on disk:[/]\n{path}")
        elif action_type == "add":
            header.update("[bold]Add Workspace Root[/]")
            tree.add_class("-hidden")
            info.remove_class("-hidden")
            info.update(
                "[dim]Extend Johnston's access beyond the main project directory.\n\n"
                "• Press [bold]Enter[/] or [bold]a[/] to add path\n"
                "• Drag & drop folder from file manager\n"
                "• Supports --project, --local, and --session scopes[/]"
            )

    def refresh_list(self) -> None:
        self.roots_data = self._load_roots()
        self._option_actions = []
        try:
            opt_list = self.query_one("#workspace-option-list", OptionList)
        except Exception:
            return

        curr_idx = opt_list.highlighted
        opt_list.clear_options()

        is_compact = False
        try:
            right_pane = self.query_one("#workspace-right-pane", Vertical)
            is_compact = right_pane.has_class("-hidden")
        except Exception:
            pass

        default_w = MODAL_MEDIUM_ROW_WIDTH if is_compact else WORKSPACE_SIDEBAR_ROW_WIDTH
        target_w = option_list_row_width(opt_list, default_w)

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
        self._update_tree_for_option(opt_list.highlighted)

    def _update_hint(self, idx: int | None = None) -> None:
        try:
            hint_widget = self.query_one(f"#{MODAL_HINT_ID}", ModalHint)
        except Exception:
            return

        is_wide = False
        try:
            right_pane = self.query_one("#workspace-right-pane", Vertical)
            is_wide = not right_pane.has_class("-hidden")
        except Exception:
            pass

        tree_focused = False
        try:
            tree = self.query_one("#workspace-dir-tree", WorkspaceDirectoryTree)
            if self.focused == tree:
                tree_focused = True
        except Exception:
            pass

        if tree_focused:
            hint_widget.update("tab Roots • enter Expand • esc Close")
            return

        tab_hint = "tab Tree • " if is_wide else ""

        if idx is None:
            try:
                opt_list = self.query_one("#workspace-option-list", OptionList)
                idx = opt_list.highlighted
            except Exception:
                idx = None

        if idx is not None and 0 <= idx < len(self._option_actions):
            action_type, data = self._option_actions[idx]
            if action_type == "add":
                hint_widget.update("enter Add • drop folder • esc Close")
                return
            if action_type == "root" and data:
                if data.get("scope") == "primary":
                    hint_widget.update(f"{tab_hint}drop folder • a Add • esc Close")
                    return
                hint_widget.update(f"{tab_hint}d Delete • a Add • esc Close")
                return

        hint_widget.update(f"{tab_hint}drop folder • a Add • esc Close")

    def on_paste(self, event: events.Paste) -> None:
        raw = event.text.strip()
        if not raw:
            return

        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        added_any = False
        for line in lines:
            clean_path = decode_pasted_path(line)
            abs_path = os.path.realpath(os.path.abspath(clean_path))
            if os.path.isdir(abs_path):
                event.stop()
                event.prevent_default()
                used_scope = self.pm.save_workspace_root(abs_path, scope="auto")
                scope_desc = {
                    "session": "session only",
                    "local": "local config",
                    "project": "project config",
                }.get(used_scope, used_scope)
                if self.app and hasattr(self.app, "notify"):
                    self.app.notify(f"Added `{abs_path}` ({scope_desc})", severity="information")
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
