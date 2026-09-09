"""Modal screen for managing git branches and worktrees."""
from __future__ import annotations

import asyncio
import os
from typing import Any

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from johnston.tui.presentation.screens.base_modal import BaseModalScreen, status_tag
from johnston.tui.presentation.screens.base_selection import HeaderWrapOptionList
from johnston.tui.presentation.screens.confirm import ConfirmScreen
from johnston.tui.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT_ID,
)
from johnston.tui.presentation.widgets.modal_header import ModalHeader
from johnston.tui.presentation.widgets.modal_hint import ModalHint
from johnston.tui.utils.key_aliases import expand_bindings
from johnston.tui.utils.responsive import (
    MODAL_MEDIUM_MAX_WIDTH,
    MODAL_MIN_WIDTH,
    apply_modal_fit,
)
from johnston.tui.utils.row_format import (
    MODAL_MEDIUM_ROW_WIDTH,
    format_badge_row,
    option_list_row_width,
)

__all__ = ["BranchScreen", "BranchInput", "BranchOptionList"]


def _item_val(item: Any, key: str, default: Any = None) -> Any:
    if isinstance(item, dict):
        return item.get(key, default)
    return getattr(item, key, default)


def _get_branch_name(item: Any) -> str:
    return str(_item_val(item, "branch") or _item_val(item, "name") or "")


def _get_path(item: Any) -> str:
    return str(_item_val(item, "path") or _item_val(item, "worktree_path") or "")


def _is_root(item: Any) -> bool:
    return bool(_item_val(item, "is_root") or False)


def _is_worktree(item: Any) -> bool:
    return bool(_item_val(item, "is_worktree") or False)


def _is_current(item: Any) -> bool:
    return bool(_item_val(item, "is_current") or _item_val(item, "is_active") or False)


def _is_remote(item: Any) -> bool:
    return bool(_item_val(item, "is_remote") or False)


def _get_badge(item: Any) -> str:
    explicit = _item_val(item, "badge")
    if explicit:
        return str(explicit)
    if _is_root(item):
        return "repo root"
    if _is_worktree(item):
        return "worktree"
    if _is_remote(item):
        return "remote"
    return "local"


def _get_mgr() -> Any:
    try:
        from johnston.core.infrastructure.runtime.git_worktree import GitWorktreeManager

        return GitWorktreeManager
    except ImportError:
        return None


class BranchInput(Input):
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


class BranchOptionList(HeaderWrapOptionList):
    """OptionList that routes boundary vertical navigation back to BranchInput."""

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


class BranchScreen(BaseModalScreen[Any]):
    """Modal screen for viewing, creating, switching, merging and deleting git branches/worktrees."""

    BINDINGS = expand_bindings([
        ("escape", "cancel", "Close"),
        ("m", "merge_branch", "Merge"),
        ("d", "delete_worktree", "Delete"),
        ("x", "delete_worktree", "Delete"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ])

    def __init__(self, project_dir: str | None = None, manager: Any = None) -> None:
        super().__init__()
        self.project_dir = project_dir
        self.manager = manager
        self.branches_data: list[Any] = []
        self._option_actions: list[tuple[str, Any]] = []
        self.current_branch_name: str = ""
        self._shown_count: int = 0

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID, classes="modal-dialog-medium"):
            yield ModalHeader("Git Branches & Worktrees", esc_hint="")
            yield BranchInput(
                placeholder="Search branch or type new name...",
                id="branch-input",
                classes="modal-input",
            )
            yield BranchOptionList(id="branch-option-list")
            yield ModalHint("enter Switch/Create • m Merge • d Delete • esc Close", id=MODAL_HINT_ID)

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
        if hasattr(self, "run_worker"):
            self.run_worker(self.refresh_list_async())
        else:
            try:
                loop = asyncio.get_running_loop()
                loop.create_task(self.refresh_list_async())
            except RuntimeError:
                pass
        try:
            inp = self.query_one("#branch-input", BranchInput)
            inp.focus()
            opt_list = self.query_one("#branch-option-list", OptionList)
            opt_list.highlighted = None
        except Exception:
            pass

    def on_resize(self, event: events.Resize) -> None:
        self._apply_dialog_fit()
        self._render_options()

    @staticmethod
    async def _list_branches(mgr: Any, project_dir: str) -> list[Any]:
        if hasattr(mgr, "list_branches_and_worktrees_async"):
            res = mgr.list_branches_and_worktrees_async(project_dir)
            if asyncio.iscoroutine(res):
                return await res
            return res
        if hasattr(mgr, "list_branches_and_worktrees"):
            return await asyncio.to_thread(mgr.list_branches_and_worktrees, project_dir)
        return []

    @staticmethod
    async def _create_wt(mgr: Any, repo_dir: str, branch_name: str) -> Any:
        if hasattr(mgr, "create_worktree_async"):
            res = mgr.create_worktree_async(repo_dir, branch_name)
            if asyncio.iscoroutine(res):
                return await res
            return res
        if hasattr(mgr, "create_worktree"):
            return await asyncio.to_thread(mgr.create_worktree, repo_dir, branch_name)
        return None

    @staticmethod
    async def _check_conflicts(mgr: Any, repo_dir: str, source: str, target: str) -> Any:
        if hasattr(mgr, "check_merge_conflicts_async"):
            res = mgr.check_merge_conflicts_async(repo_dir, source, target)
            if asyncio.iscoroutine(res):
                return await res
            return res
        if hasattr(mgr, "check_merge_conflicts"):
            return await asyncio.to_thread(mgr.check_merge_conflicts, repo_dir, source, target)
        return False

    @staticmethod
    async def _merge(mgr: Any, repo_dir: str, source: str, target: str) -> Any:
        if hasattr(mgr, "merge_branch_async"):
            res = mgr.merge_branch_async(repo_dir, source, target)
            if asyncio.iscoroutine(res):
                return await res
            return res
        if hasattr(mgr, "merge_branch"):
            return await asyncio.to_thread(mgr.merge_branch, repo_dir, source, target)
        return True

    @staticmethod
    async def _remove_wt(
        mgr: Any, repo_dir: str, wt_path: str, branch_name: str = "", delete_branch: bool = False
    ) -> Any:
        if hasattr(mgr, "remove_worktree_async"):
            res = mgr.remove_worktree_async(repo_dir, wt_path, branch_name=branch_name, delete_branch=delete_branch)
            if asyncio.iscoroutine(res):
                return await res
            return res
        if hasattr(mgr, "remove_worktree"):
            return await asyncio.to_thread(
                mgr.remove_worktree, repo_dir, wt_path, branch_name=branch_name, delete_branch=delete_branch
            )
        return None

    async def refresh_list_async(self) -> None:
        pdir = self.project_dir or getattr(self.app, "project_dir", None) or os.getcwd()
        mgr = self.manager or _get_mgr()
        if mgr:
            try:
                self.branches_data = await self._list_branches(mgr, pdir) or []
            except Exception:
                self.branches_data = []
        else:
            self.branches_data = []

        self.current_branch_name = ""
        for b in self.branches_data:
            if _is_current(b):
                self.current_branch_name = _get_branch_name(b)
                break
        if not self.current_branch_name and self.app:
            agent = getattr(self.app, "agent", None)
            self.current_branch_name = getattr(agent, "worktree_branch", "") or ""

        current_filter = ""
        try:
            inp = self.query_one("#branch-input", BranchInput)
            current_filter = inp.value
        except Exception:
            pass

        self._render_options(filter_text=current_filter)

    def _render_options(self, filter_text: str = "") -> None:
        try:
            opt_list = self.query_one("#branch-option-list", OptionList)
        except Exception:
            return

        curr_idx = opt_list.highlighted
        opt_list.clear_options()
        self._option_actions = []

        target_w = option_list_row_width(opt_list, MODAL_MEDIUM_ROW_WIDTH)

        query = filter_text.strip()
        if query:
            filtered = [b for b in self.branches_data if query.lower() in _get_branch_name(b).lower()]
            has_exact = any(query.lower() == _get_branch_name(b).lower() for b in self.branches_data)
        else:
            filtered = list(self.branches_data)
            has_exact = True

        self._shown_count = len(filtered)

        if query and not has_exact:
            prefix = "  "
            row = format_badge_row(f'+ Create worktree on "{query}"', target_width=target_w, prefix=prefix)
            opt_list.add_option(Option(row))
            self._option_actions.append(("new", {"branch": query}))
        elif not self.branches_data:
            row = format_badge_row("No git repository or branches found", badge="empty", target_width=target_w)
            opt_list.add_option(Option(row, disabled=True))
            self._option_actions.append(("empty", {}))

        for item in filtered:
            branch = _get_branch_name(item)
            is_curr = _is_current(item)
            badge = _get_badge(item)

            prefix = f"{status_tag('ACTIVE')} " if is_curr else "  "
            row = format_badge_row(branch, badge=badge, target_width=target_w, prefix=prefix)
            opt_list.add_option(Option(row))
            self._option_actions.append(("branch", item))

        is_inp_focused = False
        try:
            inp = self.query_one("#branch-input", BranchInput)
            is_inp_focused = inp.has_focus
        except Exception:
            pass

        if is_inp_focused:
            opt_list.highlighted = None
        elif curr_idx is not None and curr_idx < len(opt_list._options):
            opt_list.highlighted = curr_idx
        elif len(self._option_actions) > 0 and opt_list.has_focus:
            opt_list.highlighted = 0
        else:
            opt_list.highlighted = None

        self._update_hint()

    def _update_hint(self, idx: int | None = None) -> None:
        try:
            hint_widget = self.query_one(f"#{MODAL_HINT_ID}", ModalHint)
        except Exception:
            return

        total = len(self.branches_data)
        right_text = f"{self._shown_count}/{total}" if total > 0 else ""
        hint_widget.update("enter Switch/Create • m Merge • d Delete • esc Close", right_text=right_text)

    def on_input_changed(self, event: Input.Changed) -> None:
        self._render_options(filter_text=event.value)

    def on_descendant_focus(self, event: events.DescendantFocus) -> None:
        try:
            inp = self.query_one("#branch-input", BranchInput)
            opt_list = self.query_one("#branch-option-list", OptionList)
            if inp.has_focus:
                opt_list.highlighted = None
        except Exception:
            pass
        self._update_hint()

    def focus_input(self) -> None:
        try:
            opt_list = self.query_one("#branch-option-list", OptionList)
            opt_list.highlighted = None
            inp = self.query_one("#branch-input", BranchInput)
            inp.focus()
            self._update_hint()
        except Exception:
            pass

    def focus_first_option(self) -> None:
        try:
            opt_list = self.query_one("#branch-option-list", OptionList)
            if len(opt_list._options) > 0:
                opt_list.highlighted = 0
                opt_list.focus()
                self._update_hint(0)
        except Exception:
            pass

    def focus_last_option(self) -> None:
        try:
            opt_list = self.query_one("#branch-option-list", OptionList)
            if len(opt_list._options) > 0:
                opt_list.highlighted = len(opt_list._options) - 1
                opt_list.focus()
                self._update_hint(opt_list.highlighted)
        except Exception:
            pass

    def handle_option_list_down(self) -> bool:
        try:
            opt_list = self.query_one("#branch-option-list", OptionList)
            if opt_list.highlighted is not None and opt_list.highlighted == len(opt_list._options) - 1:
                self.focus_input()
                return True
        except Exception:
            pass
        return False

    def handle_option_list_up(self) -> bool:
        try:
            opt_list = self.query_one("#branch-option-list", OptionList)
            if opt_list.highlighted is not None and opt_list.highlighted == 0:
                self.focus_input()
                return True
        except Exception:
            pass
        return False

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self._update_hint(event.option_index)

    async def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        idx = event.option_index
        if idx is not None and 0 <= idx < len(self._option_actions):
            await self._handle_action_select(self._option_actions[idx])

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        val = event.value.strip()
        opt_list = self.query_one("#branch-option-list", OptionList)
        if opt_list.highlighted is not None and 0 <= opt_list.highlighted < len(self._option_actions):
            await self._handle_action_select(self._option_actions[opt_list.highlighted])
        elif len(self._option_actions) > 0:
            await self._handle_action_select(self._option_actions[0])
        elif val:
            await self._handle_action_select(("new", {"branch": val}))

    async def _handle_action_select(self, action_tuple: tuple[str, Any]) -> None:
        action_type, data = action_tuple
        pdir = self.project_dir or getattr(self.app, "project_dir", None) or os.getcwd()
        mgr = self.manager or _get_mgr()

        if action_type == "new":
            branch = data.get("branch", "")
            if not branch:
                return
            wt_res = await self._create_wt(mgr, pdir, branch)
            target_dir = wt_res[0] if isinstance(wt_res, (tuple, list)) else wt_res
            if target_dir:
                if hasattr(self.app, "switch_project_dir"):
                    self.app.switch_project_dir(target_dir, branch)
                self.dismiss(target_dir)
            else:
                if hasattr(self.app, "notify"):
                    self.app.notify(f"Failed to create worktree on '{branch}'", severity="error")

        elif action_type == "branch":
            branch = _get_branch_name(data)
            is_root = _is_root(data)
            is_worktree = _is_worktree(data)
            path = _get_path(data)

            if (is_root or is_worktree) and path:
                if hasattr(self.app, "switch_project_dir"):
                    self.app.switch_project_dir(path, branch)
                self.dismiss(path)
            else:
                wt_res = await self._create_wt(mgr, pdir, branch)
                target_dir = wt_res[0] if isinstance(wt_res, (tuple, list)) else wt_res
                if target_dir:
                    if hasattr(self.app, "switch_project_dir"):
                        self.app.switch_project_dir(target_dir, branch)
                    self.dismiss(target_dir)
                else:
                    if hasattr(self.app, "notify"):
                        self.app.notify(f"Failed to create worktree for '{branch}'", severity="error")

    async def action_merge_branch(self) -> None:
        try:
            inp = self.query_one("#branch-input", BranchInput)
            opt_list = self.query_one("#branch-option-list", OptionList)
            if inp.has_focus and not opt_list.has_focus:
                return
        except Exception:
            pass

        try:
            opt_list = self.query_one("#branch-option-list", OptionList)
            idx = opt_list.highlighted
        except Exception:
            return

        if idx is None or not (0 <= idx < len(self._option_actions)):
            return

        action_type, data = self._option_actions[idx]
        if action_type != "branch":
            return

        source_branch = _get_branch_name(data)
        target_branch = self.current_branch_name or "main"

        if source_branch.startswith("detached") or target_branch.startswith("detached"):
            if hasattr(self.app, "notify"):
                self.app.notify("Cannot merge detached HEAD", severity="warning")
            return

        if source_branch == target_branch:
            if hasattr(self.app, "notify"):
                self.app.notify("Cannot merge branch into itself", severity="warning")
            return

        pdir = self.project_dir or getattr(self.app, "project_dir", None) or os.getcwd()
        mgr = self.manager or _get_mgr()

        conflicts = await self._check_conflicts(mgr, pdir, source_branch, target_branch)
        has_conflicts = False
        if isinstance(conflicts, tuple):
            has_conflicts = bool(conflicts[0])
        elif isinstance(conflicts, bool):
            has_conflicts = conflicts
        elif isinstance(conflicts, (list, str)):
            has_conflicts = bool(conflicts)

        if has_conflicts:
            if hasattr(self.app, "notify"):
                self.app.notify(f"Merge conflict detected between '{source_branch}' and '{target_branch}'", severity="error")
            return

        async def on_confirm(confirmed: bool) -> None:
            if confirmed:
                merge_res = await self._merge(mgr, pdir, source_branch, target_branch)
                success = merge_res if isinstance(merge_res, bool) else getattr(merge_res, "success", True)
                if isinstance(merge_res, (tuple, list)):
                    success = bool(merge_res[0])
                if success:
                    if hasattr(self.app, "notify"):
                        self.app.notify(
                            f"Successfully merged '{source_branch}' into '{target_branch}'", severity="information"
                        )
                    await self.refresh_list_async()
                else:
                    if hasattr(self.app, "notify"):
                        self.app.notify(f"Failed to merge '{source_branch}' into '{target_branch}'", severity="error")
            try:
                self.query_one("#branch-option-list", OptionList).focus()
            except Exception:
                pass

        if hasattr(self.app, "push_screen"):
            self.app.push_screen(
                ConfirmScreen(
                    f"Merge '{source_branch}' into '{target_branch}'?",
                    message=f"Merge '{source_branch}' into '{target_branch}'?",
                    confirm_label="Merge",
                    cancel_label="Cancel",
                ),
                callback=on_confirm,
            )

    async def action_delete_worktree(self) -> None:
        try:
            inp = self.query_one("#branch-input", BranchInput)
            opt_list = self.query_one("#branch-option-list", OptionList)
            if inp.has_focus and not opt_list.has_focus:
                return
        except Exception:
            pass

        try:
            opt_list = self.query_one("#branch-option-list", OptionList)
            idx = opt_list.highlighted
        except Exception:
            return

        if idx is None or not (0 <= idx < len(self._option_actions)):
            return

        action_type, data = self._option_actions[idx]
        if action_type != "branch":
            return

        branch = _get_branch_name(data)
        is_root = _is_root(data)
        is_current = _is_current(data)
        is_worktree = _is_worktree(data)
        path = _get_path(data)

        if branch.startswith("detached"):
            if hasattr(self.app, "notify"):
                self.app.notify("Cannot delete detached HEAD", severity="warning")
            return

        if is_root:
            if hasattr(self.app, "notify"):
                self.app.notify("Cannot delete repository root", severity="warning")
            return

        if not is_worktree and not path:
            if hasattr(self.app, "notify"):
                self.app.notify(f"'{branch}' has no active worktree to delete", severity="warning")
            return

        current_dir = getattr(self.app, "project_dir", None) or os.getcwd()
        if is_current or (path and os.path.realpath(path) == os.path.realpath(current_dir)):
            if hasattr(self.app, "notify"):
                self.app.notify("Cannot delete currently active worktree", severity="warning")
            return

        pdir = self.project_dir or getattr(self.app, "project_dir", None) or os.getcwd()
        mgr = self.manager or _get_mgr()

        wt_path = path or ""

        async def on_confirm(confirmed: bool) -> None:
            if confirmed:
                await self._remove_wt(mgr, pdir, wt_path=wt_path, branch_name=branch, delete_branch=False)
                if hasattr(self.app, "notify"):
                    self.app.notify(f"Deleted worktree for '{branch}'", severity="information")
                await self.refresh_list_async()
            try:
                self.query_one("#branch-option-list", OptionList).focus()
            except Exception:
                pass

        if hasattr(self.app, "push_screen"):
            self.app.push_screen(
                ConfirmScreen(
                    f"Delete worktree for '{branch}'?",
                    message=f"Delete worktree for '{branch}'?",
                    confirm_label="Delete",
                    cancel_label="Cancel",
                ),
                callback=on_confirm,
            )
