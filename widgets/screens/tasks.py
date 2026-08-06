from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Markdown, OptionList, RichLog

from core.config import THEME_MUTED


class TaskConsoleScreen(ModalScreen[None]):
    """Modal screen for viewing console output of a specific task in real-time"""
    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "back", "Back to list"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def action_quit_app(self) -> None:
        self.app.exit()

    def __init__(self, bg_task):
        super().__init__()
        self.bg_task = bg_task
        self.printed_count = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("### **Console Output**", classes="modal-markdown")
            yield RichLog(id="console-log", highlight=False, markup=False)
            yield Label("esc: cancel", id="modal-hint")

    def on_mount(self) -> None:
        self.log_widget = self.query_one("#console-log", RichLog)
        self.log_widget.focus()
        self.update_log()
        self.set_interval(0.1, self.update_log)

    def update_log(self) -> None:
        from core.background_task import process_carriage_returns, strip_ansi
        lines = self.bg_task.output
        if len(lines) > self.printed_count:
            for i in range(self.printed_count, len(lines)):
                raw_line = lines[i].rstrip("\r\n")
                clean_line = process_carriage_returns(strip_ansi(raw_line))
                self.log_widget.write(clean_line)
            self.printed_count = len(lines)

    def action_back(self) -> None:
        self.dismiss()


class TasksListScreen(ModalScreen[None]):
    """Modal screen with background tasks list"""
    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "close", "Close Manager"),
        ("tab", "kill_task", "Kill Task"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def action_quit_app(self) -> None:
        self.app.exit()

    def __init__(self):
        super().__init__()
        self.search_query = ""
        self.filtered_tasks = []

    def _get_filtered_tasks(self) -> list:
        all_tasks = getattr(self.app, "background_tasks", [])
        curr_sid = getattr(self.app, "current_session_id", None)
        if curr_sid:
            filtered = [t for t in all_tasks if getattr(t, "session_id", None) in (curr_sid, None)]
        else:
            filtered = list(all_tasks)
        filtered = [t for t in filtered if getattr(t, "is_background", False)]
        q = self.search_query.strip().lower()
        if q:
            filtered = [
                t for t in filtered
                if q in getattr(t, "command", "").lower()
                or q in getattr(t, "task_id", "").lower()
            ]
        return sorted(filtered, key=lambda t: not getattr(t, "is_running", False))

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("### **Background Tasks Manager**", classes="modal-markdown")
            yield Input(placeholder="Search tasks...", id="modal-search-input")
            yield OptionList(id="tasks-option-list")
            yield Label("enter: view output • tab: kill task • esc: cancel", id="modal-hint")

    def on_mount(self) -> None:
        self._last_signatures = None
        self.update_tasks_list()
        try:
            self.query_one("#modal-search-input", Input).focus()
        except Exception:
            pass
        self.set_interval(0.5, self.update_tasks_list)

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "modal-search-input":
            self.search_query = event.value
            self._last_signatures = None
            self.update_tasks_list()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "modal-search-input":
            tasks = self._get_filtered_tasks()
            opt_list = self.query_one("#tasks-option-list", OptionList)
            idx = opt_list.highlighted
            if idx is not None and idx < len(tasks):
                task = tasks[idx]
                if hasattr(task, "async_task"):
                    from widgets.screens.subagent_screen import SubagentViewScreen
                    self.app.push_screen(SubagentViewScreen(task.task_id))
                else:
                    self.app.push_screen(TaskConsoleScreen(task))

    def _on_key(self, event: events.Key) -> None:
        if event.key in ("down", "up"):
            try:
                search_input = self.query_one("#modal-search-input", Input)
                if search_input.has_focus:
                    tasks = self._get_filtered_tasks()
                    opt_list = self.query_one("#tasks-option-list", OptionList)
                    if opt_list.highlighted is None and tasks:
                        opt_list.highlighted = 0
                    elif opt_list.highlighted is not None:
                        if event.key == "down":
                            opt_list.action_cursor_down()
                        else:
                            opt_list.action_cursor_up()
                    event.prevent_default()
                    event.stop()
            except Exception:
                pass

    def update_tasks_list(self) -> None:
        if not self.is_mounted:
            return
        tasks = self._get_filtered_tasks()
        new_signatures = [(getattr(t, "task_id", ""), getattr(t, "is_running", False), getattr(t, "command", "")) for t in tasks]
        if hasattr(self, "_last_signatures") and self._last_signatures == new_signatures:
            return
        self._last_signatures = new_signatures

        opt_list = self.query_one("#tasks-option-list", OptionList)
        current_highlighted = opt_list.highlighted

        opt_list.clear_options()
        if not tasks:
            opt_list.add_option(Text("No active background tasks.", style=THEME_MUTED))
            return

        for t in tasks:
            cmd = t.command
            if len(cmd) > 38:
                cmd = cmd[:35] + "..."
            status_tag = r"\[RUNNING]" if t.is_running else r"\[FINISHED]"
            opt_list.add_option(f"{status_tag} {cmd}")

        if current_highlighted is not None and current_highlighted < len(tasks):
            opt_list.highlighted = current_highlighted
        else:
            opt_list.highlighted = 0

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        tasks = self._get_filtered_tasks()
        if event.option_index is not None and event.option_index < len(tasks):
            task = tasks[event.option_index]
            if hasattr(task, "async_task"):
                from widgets.screens.subagent_screen import SubagentViewScreen
                self.app.push_screen(SubagentViewScreen(task.task_id))
            else:
                self.app.push_screen(TaskConsoleScreen(task))

    async def action_kill_task(self) -> None:
        opt_list = self.query_one("#tasks-option-list", OptionList)
        idx = opt_list.highlighted
        tasks = self._get_filtered_tasks()
        if idx is not None and idx < len(tasks):
            task = tasks[idx]
            if task.is_running:
                import inspect

                res = task.kill()
                if inspect.isawaitable(res):
                    await res
                self.update_tasks_list()

    def action_close(self) -> None:
        self.dismiss()

