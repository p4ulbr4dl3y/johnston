import time
from typing import Optional

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Label, Markdown, OptionList, RichLog
from textual.widgets.option_list import Option

from core.defaults.config import THEME_MUTED
from widgets.screens.base_modal import BaseModalScreen
from widgets.screens.base_selection import HeaderWrapOptionList
from widgets.screens.constants import MODAL_DIALOG_ID, MODAL_HINT_ID, MODAL_MARKDOWN, MODAL_MARKDOWN_CENTERED


class TaskConsoleScreen(BaseModalScreen[None]):
    """Modal screen for viewing console output of a specific task in real-time"""

    BINDINGS = [
        ("escape", "back", "Back to list"),
    ]

    def __init__(self, bg_task):
        super().__init__()
        self.bg_task = bg_task
        self.printed_count = 0

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID):
            yield Markdown("### **Console Output**", classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}")
            yield RichLog(id="console-log", highlight=False, markup=False)
            yield Label("esc: cancel", id=MODAL_HINT_ID)

    def on_mount(self) -> None:
        self.log_widget = self.query_one("#console-log", RichLog)
        self.log_widget.focus()
        self.update_log()
        self.set_interval(0.1, self.update_log)

    def update_log(self) -> None:
        from core.tasks.output import process_carriage_returns, strip_ansi

        lines = self.bg_task.output.history if hasattr(self.bg_task.output, "history") else self.bg_task.output
        if len(lines) > self.printed_count:
            for i in range(self.printed_count, len(lines)):
                raw_line = lines[i].rstrip("\r\n")
                clean_line = process_carriage_returns(strip_ansi(raw_line))
                self.log_widget.write(clean_line)
            self.printed_count = len(lines)

    def action_back(self) -> None:
        self.dismiss()


class ShellTasksScreen(BaseModalScreen[None]):
    """Modal screen listing background shell tasks with console view and kill."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("k", "kill_task", "Kill Task"),
    ]

    def __init__(self):
        super().__init__()
        self.search_query = ""
        self.filtered_tasks = []
        self._last_signatures = None

    def _get_header_md(self) -> str:
        return "### **Shell Tasks**"

    def _get_filtered_tasks(self) -> list:
        all_tasks = []
        app = self.app if (hasattr(self, "app") and self.app) else None
        if app is not None:
            all_tasks = [t for t in getattr(app, "task_manager", []) if getattr(t, "kind", "") == "shell"]
            curr_sid = getattr(app, "current_session_id", None)
            if curr_sid:
                all_tasks = [t for t in all_tasks if getattr(t, "session_id", None) == curr_sid]

        items = []
        for t in all_tasks:
            if not getattr(t, "is_background", False):
                continue
            task_id = getattr(t, "task_id", "")
            running = getattr(t, "is_running", False)
            items.append(
                {
                    "id": task_id,
                    "command": getattr(t, "command", ""),
                    "is_running": running,
                    "status_str": "RUNNING" if running else "FINISHED",
                    "raw_obj": t,
                }
            )

        q = self.search_query.strip().lower()
        if q:
            items = [it for it in items if q in it["command"].lower() or q in it["id"].lower()]

        return sorted(items, key=lambda item: not item["is_running"])

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID):
            yield Markdown(
                self._get_header_md(), id="shell-title", classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}"
            )
            yield HeaderWrapOptionList(id="shell-option-list")
            yield Label("enter: view console • k: kill • esc: cancel", id=MODAL_HINT_ID)

    def on_mount(self) -> None:
        self._last_signatures = None
        self.update_tasks_list()
        try:
            self.query_one("#shell-option-list", OptionList).focus()
        except Exception:
            pass
        self.set_interval(0.5, self.update_tasks_list)

    def update_tasks_list(self) -> None:
        if not self.is_mounted:
            return
        tasks = self._get_filtered_tasks()
        new_signatures = [(item["id"], item["is_running"], item["command"]) for item in tasks]
        if self._last_signatures == new_signatures:
            return
        self._last_signatures = new_signatures

        opt_list = self.query_one("#shell-option-list", OptionList)
        current_highlighted = opt_list.highlighted

        opt_list.clear_options()
        if not tasks:
            opt_list.add_option(Text("No shell tasks found.", style=THEME_MUTED))
            self.filtered_tasks = []
            return

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
                opt_list.add_option(self._format_task_row(item))
                self.filtered_tasks.append(item)

        if current_highlighted is not None and 0 <= current_highlighted < len(self.filtered_tasks):
            highlighted_item = self.filtered_tasks[current_highlighted]
            opt_list.highlighted = current_highlighted if highlighted_item is not None else 0
        else:
            for i, it in enumerate(self.filtered_tasks):
                if it is not None:
                    opt_list.highlighted = i
                    break

    def _format_task_row(self, item: dict) -> str:
        cmd = item["command"]
        if len(cmd) > 35:
            cmd = cmd[:32] + "..."
        return f"   {cmd}".rstrip()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.filtered_tasks):
            item = self.filtered_tasks[event.option_index]
            if item is not None:
                self.app.push_screen(TaskConsoleScreen(item["raw_obj"]))

    async def action_kill_task(self) -> None:
        opt_list = self.query_one("#shell-option-list", OptionList)
        idx = opt_list.highlighted
        if idx is not None and 0 <= idx < len(self.filtered_tasks):
            item = self.filtered_tasks[idx]
            if item is None:
                return
            raw = item["raw_obj"]
            if getattr(raw, "is_running", False):
                import inspect

                res = raw.kill()
                if inspect.isawaitable(res):
                    await res
            self._last_signatures = None
            self.update_tasks_list()

    def action_close(self) -> None:
        self.dismiss()


class SubagentsScreen(BaseModalScreen[None]):
    """Modal screen listing running/completed subagents with detail view and kill."""

    BINDINGS = [
        ("escape", "close", "Close"),
        ("k", "kill_task", "Kill Task"),
    ]

    def __init__(self):
        super().__init__()
        self.search_query = ""
        self.filtered_tasks = []
        # Cache of the last _get_filtered_tasks() result to avoid re-reading the
        # session store / disk on every 0.5s ticker invocation.
        self._cached_tasks: list = []
        self._tasks_cache_ts: Optional[float] = None
        self._tasks_cache_ttl: float = 0.5

    def _get_header_md(self) -> str:
        return "### **Subagents**"

    def _get_option_list(self) -> OptionList:
        return self.query_one("#subagents-option-list", OptionList)

    def _invalidate_tasks_cache(self) -> None:
        """Drop the cached filtered-tasks snapshot so the next read re-reads the store."""
        self._tasks_cache_ts = None

    def _get_filtered_tasks(self) -> list:
        now = time.monotonic()
        if (
            self._tasks_cache_ts is not None
            and now - self._tasks_cache_ts < self._tasks_cache_ttl
            and self._cached_tasks is not None
        ):
            return self._cached_tasks

        items = []

        store = getattr(self.app, "sm", None) if (hasattr(self, "app") and self.app) else None
        if store is None:
            from core.session_manager import SessionStore

            store = SessionStore.get_instance()

        curr_sid = getattr(self.app, "current_session_id", None) if (hasattr(self, "app") and self.app) else None
        sessions = store.get_subagents_for_parent(curr_sid) if curr_sid else store.list(kind="subagent")

        for s in sessions:
            st_str = (getattr(s, "status", "") or "unknown").upper()
            is_run = st_str == "RUNNING"
            items.append(
                {
                    "id": getattr(s, "id", ""),
                    "command": getattr(s, "description", None) or getattr(s, "prompt", None) or getattr(s, "id", ""),
                    "is_running": is_run,
                    "status_str": st_str,
                    "raw_obj": s,
                }
            )

        # Filter by search query
        q = self.search_query.strip().lower()
        if q:
            items = [
                item
                for item in items
                if q in item["command"].lower() or q in item["id"].lower()
            ]

        result = sorted(items, key=lambda item: not item["is_running"])
        self._cached_tasks = result
        self._tasks_cache_ts = time.monotonic()
        return result

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID):
            yield Markdown(
                self._get_header_md(), id="subagents-title", classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}"
            )
            yield HeaderWrapOptionList(id="subagents-option-list")
            yield Label("enter: view details • k: kill • esc: cancel", id=MODAL_HINT_ID)

    def on_mount(self) -> None:
        self._last_signatures = None
        self.update_tasks_list()
        try:
            self._get_option_list().focus()
        except Exception:
            pass
        self.set_interval(0.5, self.update_tasks_list)

    def update_tasks_list(self) -> None:
        if not self.is_mounted:
            return
        tasks = self._get_filtered_tasks()
        new_signatures = [(item["id"], item["is_running"], item["command"]) for item in tasks]
        if hasattr(self, "_last_signatures") and self._last_signatures == new_signatures:
            return
        self._last_signatures = new_signatures

        opt_list = self._get_option_list()
        current_highlighted = opt_list.highlighted

        opt_list.clear_options()
        if not tasks:
            opt_list.add_option(Text("No subagents found.", style=THEME_MUTED))
            self.filtered_tasks = []
            return

        # Build display rows in lockstep with self.filtered_tasks: a None marks a
        # group header (Running / Completed), a dict marks a real subagent.
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
                opt_list.add_option(self._format_task_row(item))
                self.filtered_tasks.append(item)

        if current_highlighted is not None and 0 <= current_highlighted < len(self.filtered_tasks):
            highlighted_item = self.filtered_tasks[current_highlighted]
            opt_list.highlighted = current_highlighted if highlighted_item is not None else 0
        else:
            # First selectable (non-header) row
            for i, it in enumerate(self.filtered_tasks):
                if it is not None:
                    opt_list.highlighted = i
                    break

    def _format_task_row(self, item: dict) -> str:
        cmd = item["command"]
        if len(cmd) > 35:
            cmd = cmd[:32] + "..."
        return f"   {cmd}".rstrip()

    def _open_task_details(self, item: dict) -> None:
        from widgets.screens.subagent_screen import SubagentViewScreen

        session_id = getattr(item["raw_obj"], "id", item["id"])
        self.app.push_screen(SubagentViewScreen(session_id))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.filtered_tasks):
            item = self.filtered_tasks[event.option_index]
            if item is not None:
                self._open_task_details(item)

    async def action_kill_task(self) -> None:
        opt_list = self._get_option_list()
        idx = opt_list.highlighted
        if idx is not None and 0 <= idx < len(self.filtered_tasks):
            item = self.filtered_tasks[idx]
            if item is None:
                return
            sess = item["raw_obj"]
            if getattr(sess, "status", "") == "running" or getattr(sess, "is_running", False):
                if getattr(sess, "async_task", None) and not sess.async_task.done():
                    try:
                        sess.async_task.cancel()
                    except Exception:
                        pass
                if hasattr(sess, "finish"):
                    sess.finish("cancelled", "Terminated from subagents menu")
            self._last_signatures = None
            self._invalidate_tasks_cache()
            self.update_tasks_list()

    def action_close(self) -> None:
        self.dismiss()
