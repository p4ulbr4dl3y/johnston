import time
from typing import Any, Optional

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, Markdown, OptionList, RichLog
from textual.widgets.option_list import Option

from core.infrastructure.presentation.tool_display import (
    extract_subagent_progress,
    is_subagent_running,
)
from core.infrastructure.tasks.output import process_carriage_returns, strip_ansi
from widgets.presentation.screens.base_modal import BaseModalScreen
from widgets.presentation.screens.base_selection import HeaderWrapOptionList
from widgets.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT_ID,
    MODAL_MARKDOWN,
    MODAL_MARKDOWN_CENTERED,
)
from widgets.utils.key_aliases import expand_bindings
from widgets.utils.row_format import MODAL_MEDIUM_ROW_WIDTH, format_badge_row, option_list_row_width


def _format_duration(seconds: float) -> str:
    if seconds < 0:
        seconds = 0.0
    if seconds < 60:
        if seconds < 10:
            return f"{seconds:.1f}s"
        return f"{int(seconds)}s"
    minutes = int(seconds // 60)
    secs = int(seconds % 60)
    return f"{minutes}m {secs:02d}s"


def extract_shell_task_progress(task: Any) -> str:
    """Extract a short, human-like activity/status badge for a background shell task."""
    if task is None:
        return ""

    is_running = getattr(task, "is_running", False)
    now = time.time()
    created_at = getattr(task, "created_at", None)

    if is_running:
        if created_at and isinstance(created_at, (int, float)) and created_at > 0:
            dur = _format_duration(max(0.0, now - created_at))
            return f"running • {dur}"
        return "running..."

    # Terminal state
    status = getattr(task, "status", None)
    st_str = (status.value if hasattr(status, "value") else str(status or "")).lower()
    was_killed = getattr(task, "was_killed", False) or st_str == "killed"

    if was_killed:
        return "killed"
    if st_str == "timeout":
        return "timeout"

    completed_at = getattr(task, "completed_at", None)
    dur_str = ""
    if created_at and completed_at and isinstance(created_at, (int, float)) and isinstance(completed_at, (int, float)):
        dur_str = f" • {_format_duration(max(0.0, completed_at - created_at))}"

    exit_code = getattr(task, "exit_code", None)
    if exit_code is None and getattr(task, "process", None) is not None:
        exit_code = getattr(task.process, "returncode", None)

    if exit_code is not None:
        return f"exit {exit_code}{dur_str}"

    if st_str in ("completed", "finished", "done"):
        return f"exit 0{dur_str}"
    if st_str == "error":
        return f"exit 1{dur_str}"

    return st_str or "done"


def format_shell_task_row(
    cmd: str, task: Optional[object] = None, is_running: bool = False, target_width: int = MODAL_MEDIUM_ROW_WIDTH
) -> str:
    """Format a shell task row with human-like activity/status badge on the right."""
    clean = " ".join(cmd.replace("\n", " ").replace("\r", " ").split()) or "(shell task)"
    badge_plain = (
        extract_shell_task_progress(task)
        if task is not None
        else ("running..." if is_running else "done")
    )
    return format_badge_row(clean, badge_plain, target_width=target_width)


def format_subagent_task_row(
    cmd: str, session: Optional[object] = None, is_running: bool = False, target_width: int = MODAL_MEDIUM_ROW_WIDTH
) -> str:
    """Format a subagent row with human-like activity/status badge on the right."""
    clean = " ".join(cmd.replace("\n", " ").replace("\r", " ").split()) or "(subagent task)"
    badge_plain = (
        extract_subagent_progress(session)
        if session is not None
        else ("running..." if is_running else "done")
    )
    return format_badge_row(clean, badge_plain, target_width=target_width)


def _filter_and_sort_tasks(items: list, search_query: str) -> list:
    """Apply text search filter and running-first ordering to task rows."""
    q = search_query.strip().lower()
    if q:
        items = [it for it in items if q in it["command"].lower() or q in it["id"].lower()]
    return sorted(items, key=lambda item: not item["is_running"])


class TaskConsoleScreen(BaseModalScreen[None]):
    """Modal screen for viewing console output of a specific task in real-time.

    Push-based: subscribes to the task's output listeners on mount, backfills
    the buffered history once, then renders live chunks as they arrive. No
    polling, no missed tail on buffer overflow.
    """

    BINDINGS = expand_bindings([
        ("escape", "back", "Back to list"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ])

    def __init__(self, bg_task):
        super().__init__()
        self.bg_task = bg_task
        self.log_widget = None
        self._pending_line = ""

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID, classes="modal-dialog-wide"):
            yield Markdown("### **Console Output**", classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}")
            yield RichLog(id="console-log", highlight=False, markup=False, auto_scroll=False)
            yield Label("esc: back", id=MODAL_HINT_ID)

    def on_mount(self) -> None:
        self.log_widget = self.query_one("#console-log", RichLog)
        self.log_widget.auto_scroll = False
        self.log_widget.focus()
        # Backfill the history already buffered, then go live: subscribing after
        # the synchronous backfill keeps the two ordered in the event loop.
        for chunk in self.bg_task.output.history:
            self._consume(strip_ansi(chunk))
        self.log_widget.scroll_end(animate=False)
        self.bg_task.add_listener(self._on_output)

    def on_unmount(self) -> None:
        if self.bg_task is not None:
            self.bg_task.remove_listener(self._on_output)

    def _is_at_bottom(self, threshold: int = 2) -> bool:
        if not self.log_widget:
            return True
        return (self.log_widget.max_scroll_y - self.log_widget.scroll_y) <= threshold

    def _on_output(self, text: str) -> None:
        """Live chunk from the task; the final empty signal flushes the tail."""
        if text:
            self._consume(text)
        else:
            self._flush_pending()

    def _consume(self, text: str) -> None:
        """Accumulate partial lines; write each completed line to the log.

        Chunks arrive at arbitrary boundaries, so a line that crosses a chunk
        boundary is buffered until its newline (or the final flush signal)
        arrives.
        """
        combined = self._pending_line + text
        parts = combined.split("\n")
        self._pending_line = parts.pop()
        at_bottom = self._is_at_bottom()
        for line in parts:
            self.log_widget.write(process_carriage_returns(line), scroll_end=at_bottom)

    def _flush_pending(self) -> None:
        if self._pending_line:
            at_bottom = self._is_at_bottom()
            self.log_widget.write(process_carriage_returns(self._pending_line), scroll_end=at_bottom)
            self._pending_line = ""

    def action_back(self) -> None:
        self.dismiss()


class BaseTasksListScreen(BaseModalScreen[None]):
    """Base modal screen for listing and managing background items (shell tasks, subagents)."""

    BINDINGS = expand_bindings([
        ("escape", "close", "Close"),
        ("k", "kill_task", "Kill Task"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ])

    title_id: str = "tasks-title"
    option_list_id: str = "tasks-option-list"
    hint_action_name: str = "enter: select"

    def __init__(self):
        super().__init__()
        self.search_query = ""
        self.filtered_tasks = []
        self._last_signatures = None

    def _get_header_md(self) -> str:
        raise NotImplementedError

    def _row_width(self) -> int:
        """Visible content width of the option list for right-aligned badges."""
        try:
            opt = self._get_option_list()
        except Exception:
            opt = self
        return option_list_row_width(opt, MODAL_MEDIUM_ROW_WIDTH)

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
        with Vertical(id=MODAL_DIALOG_ID, classes="modal-dialog-medium"):
            yield Markdown(
                self._get_header_md(), id=self.title_id, classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}"
            )
            yield HeaderWrapOptionList(id=self.option_list_id)
            yield Label(f"{self.hint_action_name} • ↑↓: nav • esc: close", id=MODAL_HINT_ID)

    def on_mount(self) -> None:
        self._last_signatures = None
        self.update_tasks_list()
        try:
            self._get_option_list().focus()
        except Exception:
            pass
        self.set_interval(0.5, self.update_tasks_list)

    def _update_hint(self) -> None:
        try:
            from widgets.utils.responsive import BREAKPOINT_HINT, resolve_screen_width

            is_compact = resolve_screen_width(self) < BREAKPOINT_HINT
            opt_list = self._get_option_list()
            hint = self.query_one(f"#{MODAL_HINT_ID}", Label)
            idx = opt_list.highlighted
            is_running = False
            if idx is not None and 0 <= idx < len(self.filtered_tasks):
                item = self.filtered_tasks[idx]
                if item and item.get("is_running"):
                    is_running = True

            action_short = self.hint_action_name.split(":")[0]
            if is_compact:
                hint_str = (
                    f"{action_short} • k: kill • esc"
                    if is_running
                    else f"{action_short} • ↑↓ • esc"
                )
            else:
                hint_str = (
                    f"{self.hint_action_name} • ↑↓: nav • k: kill • esc: close"
                    if is_running
                    else f"{self.hint_action_name} • ↑↓: nav • esc: close"
                )
            hint.update(hint_str)
        except Exception:
            pass

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        self._update_hint()

    def on_resize(self, event: events.Resize) -> None:
        self._last_signatures = None
        self.update_tasks_list()

    def update_tasks_list(self) -> None:
        if not self.is_mounted:
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
            self.filtered_tasks = []
            self.dismiss()
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
            self._last_signatures = None
            self.update_tasks_list()

    def action_close(self) -> None:
        self.dismiss()


class ShellTasksScreen(BaseTasksListScreen):
    """Modal screen listing background shell tasks with console view and kill."""

    title_id = "shell-title"
    option_list_id = "shell-option-list"
    hint_action_name = "enter: console"

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
                }
            )

        return _filter_and_sort_tasks(items, self.search_query)

    def _format_task_row(self, item: dict, target_width: int) -> str:
        return format_shell_task_row(
            item["command"],
            task=item.get("raw_obj"),
            is_running=item.get("is_running", False),
            target_width=target_width,
        )

    def _on_task_selected(self, item: dict) -> None:
        self.app.push_screen(TaskConsoleScreen(item["raw_obj"]))

    async def _kill_item(self, item: dict) -> None:
        raw = item["raw_obj"]
        if getattr(raw, "is_running", False):
            import inspect

            res = raw.kill()
            if inspect.isawaitable(res):
                await res


class SubagentsScreen(BaseTasksListScreen):
    """Modal screen listing running/completed subagents with detail view and kill."""

    title_id = "subagents-title"
    option_list_id = "subagents-option-list"
    hint_action_name = "enter: details"

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
        from core.session_manager import get_session_store

        store = get_session_store(self.app)
        curr_sid = getattr(self.app, "current_session_id", None) if (hasattr(self, "app") and self.app) else None
        sessions = store.children(curr_sid) if curr_sid else store.list(kind="subagent")
        self._sync_session_listeners(sessions)

        for s in sessions:
            st_str = (getattr(s, "status", "") or "unknown").upper()
            is_run = is_subagent_running(s)
            badge = extract_subagent_progress(s)
            items.append(
                {
                    "id": getattr(s, "id", ""),
                    "command": getattr(s, "description", None) or getattr(s, "prompt", None) or getattr(s, "id", ""),
                    "is_running": is_run,
                    "status_str": st_str,
                    "progress_badge": badge,
                    "raw_obj": s,
                }
            )

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
