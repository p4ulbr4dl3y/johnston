import inspect
import time
from typing import Any, Optional

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from widgets.presentation.screens.base_modal import BaseModalScreen
from widgets.presentation.screens.base_selection import HeaderWrapOptionList, ModalSearchNavMixin
from widgets.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT_ID,
    MODAL_SEARCH_INPUT,
    MODAL_SEARCH_INPUT_ID,
    TAB_KEYS,
)
from widgets.presentation.screens.task_console import (
    TaskConsoleScreen,
    TaskStdinInput,
)
from widgets.presentation.screens.tasks_formatting import (
    _filter_and_sort_tasks,
    _safe_timestamp,
    extract_shell_task_progress,
    format_shell_task_row,
    format_subagent_task_row,
)
from widgets.presentation.tool_display import (
    extract_subagent_progress,
    is_subagent_running,
)
from widgets.presentation.widgets.modal_header import ModalHeader
from widgets.presentation.widgets.modal_hint import ModalHint
from widgets.utils.key_aliases import expand_bindings
from widgets.utils.responsive import fit_modal_dialog
from widgets.utils.row_format import (
    MODAL_WIDE_ROW_WIDTH,
    option_list_row_width,
)

__all__ = [
    "extract_shell_task_progress",
    "format_shell_task_row",
    "format_subagent_task_row",
    "_safe_timestamp",
    "_filter_and_sort_tasks",
    "TaskStdinInput",
    "TaskConsoleScreen",
    "BaseTasksListScreen",
    "ShellTasksScreen",
    "SubagentsScreen",
]


class BaseTasksListScreen(ModalSearchNavMixin, BaseModalScreen[None]):
    """Base modal screen for listing and managing background items (shell tasks, subagents)."""

    BINDINGS = expand_bindings([
        ("escape", "close", "Close"),
        ("ctrl+k", "kill_task", "Kill Task"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ])

    title_id: str = "tasks-title"
    option_list_id: str = "tasks-option-list"
    hint_action_name: str = "enter Select"
    search_nav_filtered_attr: str = "filtered_tasks"

    def __init__(self):
        super().__init__()
        self.search_query = ""
        self.filtered_tasks = []
        self.total_tasks_count = 0
        self._last_signatures = None
        self.search_nav_option_list_id = self.option_list_id

    def _get_header_md(self) -> str:
        raise NotImplementedError

    def _row_width(self) -> int:
        """Visible content width of the option list for right-aligned badges."""
        try:
            opt = self._get_option_list()
        except Exception:
            opt = self
        return option_list_row_width(opt, MODAL_WIDE_ROW_WIDTH)

    def _get_option_list(self) -> OptionList:
        return self.query_one(f"#{self.option_list_id}", OptionList)

    def _get_filtered_tasks(self) -> list:
        raise NotImplementedError

    def _format_task_row(self, item: dict, target_width: int) -> str:
        raise NotImplementedError

    def _on_task_selected(self, item: dict) -> None:
        raise NotImplementedError

    async def _kill_item(self, item: dict) -> None:
        raise NotImplementedError

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID, classes="modal-dialog-wide"):
            yield ModalHeader(self._get_header_md(), esc_hint="", id=self.title_id)
            yield Input(placeholder="Search...", id=MODAL_SEARCH_INPUT_ID, classes="modal-input")
            yield HeaderWrapOptionList(id=self.option_list_id)
            yield ModalHint(f"{self.hint_action_name} • esc Close", id=MODAL_HINT_ID)

    def _apply_dialog_fit(self) -> None:
        try:
            dialog = self.query_one(f"#{MODAL_DIALOG_ID}")
            screen_h = self.app.size.height if getattr(self, "app", None) else 24
            if not isinstance(screen_h, int) or screen_h <= 0:
                screen_h = 24

            usable_h = fit_modal_dialog(dialog, screen_h)
            overhead = 8 if screen_h < 18 else 10

            opt_list = self._get_option_list()
            opt_list.styles.max_height = max(2, min(12, usable_h - overhead))
        except Exception:
            pass

    def on_mount(self) -> None:
        self.search_nav_option_list_id = self.option_list_id
        self._last_signatures = None
        self._apply_dialog_fit()
        self.update_tasks_list()
        try:
            self.query_one(MODAL_SEARCH_INPUT, Input).focus()
        except Exception:
            try:
                self._get_option_list().focus()
            except Exception:
                pass
        self.set_interval(0.5, self.update_tasks_list)

    def on_input_changed(self, event: Input.Changed) -> None:
        self.search_query = event.value
        self._last_signatures = None
        if hasattr(self, "_invalidate_tasks_cache"):
            self._invalidate_tasks_cache()
        self.update_tasks_list()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        opt_list = self._get_option_list()
        idx = opt_list.highlighted
        if idx is not None and 0 <= idx < len(self.filtered_tasks):
            item = self.filtered_tasks[idx]
            if item is not None:
                self._on_task_selected(item)
                return
        for item in self.filtered_tasks:
            if item is not None:
                self._on_task_selected(item)
                return

    def _on_key(self, event: events.Key) -> None:
        if event.key in TAB_KEYS:
            event.prevent_default()
            event.stop()
            return
        if self._handle_search_navigation(event):
            return

    def _update_hint(self) -> None:
        try:
            from widgets.utils.responsive import BREAKPOINT_HINT, resolve_screen_width

            is_compact = resolve_screen_width(self) < BREAKPOINT_HINT
            opt_list = self._get_option_list()
            hint = self.query_one(f"#{MODAL_HINT_ID}", ModalHint)
            idx = opt_list.highlighted
            is_running = False
            if idx is not None and 0 <= idx < len(self.filtered_tasks):
                item = self.filtered_tasks[idx]
                if item and item.get("is_running"):
                    is_running = True

            action_short = (
                self.hint_action_name.partition(":")[0]
                if ":" in self.hint_action_name
                else self.hint_action_name.partition(" ")[0]
            ).strip()
            if is_compact:
                hint_str = (
                    f"{action_short} • ctrl+k Kill • esc"
                    if is_running
                    else f"{action_short} • esc"
                )
            else:
                hint_str = (
                    f"{self.hint_action_name} • ctrl+k Kill • esc Close"
                    if is_running
                    else f"{self.hint_action_name} • esc Close"
                )
            shown = sum(1 for it in self.filtered_tasks if it is not None)
            total = getattr(self, "total_tasks_count", shown)
            hint.update(hint_str, right_text=f"{shown}/{total}")
        except Exception:
            pass

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self._update_hint()

    def on_resize(self, event: events.Resize) -> None:
        self._last_signatures = None
        self._apply_dialog_fit()
        self.update_tasks_list()

    def update_tasks_list(self) -> None:
        if not self.is_mounted or getattr(self, "_is_dismissed", False):
            return
        tasks = self._get_filtered_tasks()
        row_width = self._row_width()
        new_signatures = [
            (item["id"], item["is_running"], item["command"], item.get("progress_badge", ""), row_width)
            for item in tasks
        ]
        if hasattr(self, "_last_signatures") and self._last_signatures == new_signatures:
            return
        self._last_signatures = new_signatures

        if not tasks:
            if not self.search_query:
                self.filtered_tasks = []
                self.dismiss()
                return
            try:
                opt_list = self._get_option_list()
                opt_list.clear_options()
            except Exception:
                pass
            self.filtered_tasks = []
            self._update_hint()
            return

        try:
            opt_list = self._get_option_list()
        except Exception:
            return
        current_highlighted = opt_list.highlighted

        opt_list.clear_options()

        self.filtered_tasks = []
        first_group = True
        for status_key, group in (("running", [t for t in tasks if t["is_running"]]),
                                  ("completed", [t for t in tasks if not t["is_running"]])):
            if not group:
                continue
            if not first_group:
                opt_list.add_option(Option("", disabled=True))
                self.filtered_tasks.append(None)
            first_group = False
            opt_list.add_option(Option(status_key.capitalize(), disabled=True))
            self.filtered_tasks.append(None)
            for item in group:
                opt_list.add_option(self._format_task_row(item, row_width))
                self.filtered_tasks.append(item)

        if current_highlighted is not None and 0 <= current_highlighted < len(self.filtered_tasks):
            highlighted_item = self.filtered_tasks[current_highlighted]
            opt_list.highlighted = current_highlighted if highlighted_item is not None else 0
        else:
            for i, it in enumerate(self.filtered_tasks):
                if it is not None:
                    opt_list.highlighted = i
                    break
        self._update_hint()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.filtered_tasks):
            item = self.filtered_tasks[event.option_index]
            if item is not None:
                self._on_task_selected(item)

    async def action_kill_task(self) -> None:
        opt_list = self._get_option_list()
        idx = opt_list.highlighted
        if idx is not None and 0 <= idx < len(self.filtered_tasks):
            item = self.filtered_tasks[idx]
            if item is None:
                return
            await self._kill_item(item)
            if getattr(self, "_is_dismissed", False) or not self.is_mounted:
                return
            self._last_signatures = None
            self.update_tasks_list()

    def action_close(self) -> None:
        self.dismiss()


class ShellTasksScreen(BaseTasksListScreen):
    """Modal screen listing background shell tasks with separate TaskConsoleScreen modal."""

    title_id = "shell-title"
    option_list_id = "shell-option-list"
    hint_action_name = "enter Console"

    def __init__(self):
        super().__init__()
        self._observed_tasks: set = set()

    def _get_header_md(self) -> str:
        return "### **Shell Tasks**"

    def _on_task_event(self, _text: str = "") -> None:
        if hasattr(self, "app") and self.app and self.is_mounted:
            try:
                self.app.call_from_thread(self.update_tasks_list)
            except Exception:
                try:
                    self.update_tasks_list()
                except Exception:
                    pass

    def _sync_task_listeners(self, tasks: list) -> None:
        for t in tasks:
            if hasattr(t, "add_listener") and t not in self._observed_tasks:
                try:
                    t.add_listener(self._on_task_event)
                    self._observed_tasks.add(t)
                except Exception:
                    pass

    def on_unmount(self) -> None:
        for t in list(self._observed_tasks):
            if hasattr(t, "remove_listener"):
                try:
                    t.remove_listener(self._on_task_event)
                except Exception:
                    pass
        self._observed_tasks.clear()

    def _get_filtered_tasks(self) -> list:
        all_tasks = []
        app = self.app if (hasattr(self, "app") and self.app) else None
        if app is not None:
            all_tasks = [t for t in getattr(app, "task_manager", []) if getattr(t, "kind", "") == "shell"]
            curr_sid = getattr(app, "current_session_id", None)
            if curr_sid:
                all_tasks = [t for t in all_tasks if getattr(t, "session_id", None) == curr_sid]

        self._sync_task_listeners(all_tasks)

        items = []
        for t in all_tasks:
            if not getattr(t, "is_background", False):
                continue
            task_id = getattr(t, "task_id", "")
            running = getattr(t, "is_running", False)
            badge = extract_shell_task_progress(t)
            items.append(
                {
                    "id": task_id,
                    "command": getattr(t, "command", ""),
                    "is_running": running,
                    "status_str": "RUNNING" if running else "FINISHED",
                    "progress_badge": badge,
                    "raw_obj": t,
                    "created_at": getattr(t, "created_at", 0.0),
                }
            )

        self.total_tasks_count = len(items)
        return _filter_and_sort_tasks(items, self.search_query)

    def _format_task_row(self, item: dict, target_width: int) -> str:
        return format_shell_task_row(
            item["command"],
            task=item.get("raw_obj"),
            is_running=item.get("is_running", False),
            target_width=target_width,
        )

    def _on_task_selected(self, item: dict) -> None:
        raw = item.get("raw_obj")
        if raw is not None:
            try:
                app = self.app
            except Exception:
                app = getattr(self, "_app", None)
            if app:
                app.push_screen(TaskConsoleScreen(raw))

    async def _kill_item(self, item: dict) -> None:
        raw = item["raw_obj"]
        if getattr(raw, "is_running", False):
            res = raw.kill()
            if inspect.isawaitable(res):
                await res


class SubagentsScreen(BaseTasksListScreen):
    """Modal screen listing running/completed subagents with detail view and kill."""

    title_id = "subagents-title"
    option_list_id = "subagents-option-list"
    hint_action_name = "enter Details"

    def __init__(self):
        super().__init__()
        self._cached_tasks: list = []
        self._tasks_cache_ts: Optional[float] = None
        self._tasks_cache_ttl: float = 0.5
        self._observed_sessions: set = set()

    def _get_header_md(self) -> str:
        return "### **Subagents**"

    def _invalidate_tasks_cache(self) -> None:
        """Drop the cached filtered-tasks snapshot so the next read re-reads the store."""
        self._tasks_cache_ts = None

    def _on_session_event(self, _event: Any = None) -> None:
        self._invalidate_tasks_cache()
        if hasattr(self, "app") and self.app and self.is_mounted:
            try:
                self.app.call_from_thread(self.update_tasks_list)
            except Exception:
                try:
                    self.update_tasks_list()
                except Exception:
                    pass

    def _sync_session_listeners(self, sessions: list) -> None:
        for s in sessions:
            if hasattr(s, "add_listener") and s not in self._observed_sessions:
                try:
                    s.add_listener(self._on_session_event)
                    self._observed_sessions.add(s)
                except Exception:
                    pass

    def on_unmount(self) -> None:
        for s in list(self._observed_sessions):
            if hasattr(s, "remove_listener"):
                try:
                    s.remove_listener(self._on_session_event)
                except Exception:
                    pass
        self._observed_sessions.clear()

    def _get_filtered_tasks(self) -> list:
        now = time.monotonic()
        if (
            self._tasks_cache_ts is not None
            and now - self._tasks_cache_ts < self._tasks_cache_ttl
            and self._cached_tasks is not None
        ):
            return self._cached_tasks

        items = []
        from core.infrastructure.storage.session_store import get_session_store

        store = get_session_store(self.app)
        curr_sid = getattr(self.app, "current_session_id", None) if (hasattr(self, "app") and self.app) else None
        sessions = store.children(curr_sid) if curr_sid else store.list(kind="subagent")
        self._sync_session_listeners(sessions)

        for s in sessions:
            st_str = (getattr(s, "status", "") or "unknown").upper()
            is_run = is_subagent_running(s)
            badge = extract_subagent_progress(s)
            title_text = (
                getattr(s, "title", "")
                or getattr(s, "prompt", "")
                or getattr(s, "id", "")
                or "(subagent task)"
            ).strip()
            clean_title = " ".join(title_text.split()) or "(subagent task)"
            agent = getattr(s, "agent", None)
            raw_rn = getattr(agent, "role_name", None) or getattr(s, "role_name", None)
            role_display = raw_rn if (isinstance(raw_rn, str) and raw_rn.strip()) else None
            if not role_display:
                role = getattr(agent, "role", None) if agent else getattr(s, "role", None)
                if role and isinstance(role, str) and role.strip() and role.strip().lower() not in ("worker", "subagent", "default"):
                    from core.role_registry import get_role_display_name

                    role_display = get_role_display_name(role)
            if role_display and isinstance(role_display, str) and role_display.lower() not in ("worker", "subagent", "default"):
                if not clean_title.lower().startswith(role_display.lower()):
                    display_cmd = f"{role_display}: {clean_title}"
                else:
                    display_cmd = clean_title
            else:
                display_cmd = clean_title

            items.append(
                {
                    "id": getattr(s, "id", ""),
                    "command": display_cmd,
                    "is_running": is_run,
                    "status_str": st_str,
                    "progress_badge": badge,
                    "raw_obj": s,
                    "created_at": getattr(s, "created_at", 0.0),
                }
            )

        self.total_tasks_count = len(items)
        result = _filter_and_sort_tasks(items, self.search_query)
        self._cached_tasks = result
        self._tasks_cache_ts = time.monotonic()
        return result

    def _format_task_row(self, item: dict, target_width: int) -> str:
        return format_subagent_task_row(
            item["command"],
            session=item.get("raw_obj"),
            is_running=item.get("is_running", False),
            target_width=target_width,
        )

    def _open_task_details(self, item: dict) -> None:
        from widgets.presentation.screens.subagent_screen import SubagentViewScreen

        session_id = getattr(item["raw_obj"], "id", item["id"])
        self.app.push_screen(SubagentViewScreen(session_id, from_tasks=True))

    def _on_task_selected(self, item: dict) -> None:
        self._open_task_details(item)

    async def _kill_item(self, item: dict) -> None:
        sess = item["raw_obj"]
        if is_subagent_running(sess):
            if getattr(sess, "async_task", None) and not sess.async_task.done():
                try:
                    sess.async_task.cancel()
                except Exception:
                    pass
            if hasattr(sess, "finish"):
                sess.finish("cancelled", "Terminated from subagents menu")
        self._invalidate_tasks_cache()
        self._on_session_event()
