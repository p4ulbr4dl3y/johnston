from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Markdown, OptionList, RichLog

from core.config import THEME_MUTED, THEME_PRIMARY


class TaskConsoleScreen(ModalScreen[None]):
    """Modal screen for viewing console output of a specific task in real-time"""
    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "back", "Back to list"),
    ]

    def __init__(self, bg_task):
        super().__init__()
        self.bg_task = bg_task
        self.printed_count = 0

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown(f"### **Console Output: `{self.bg_task.command}`**", classes="modal-markdown")
            yield RichLog(id="console-log", highlight=True, markup=True)
            yield Label("esc: back to tasks", id="modal-hint")

    def on_mount(self) -> None:
        self.log_widget = self.query_one("#console-log", RichLog)
        self.log_widget.focus()
        self.update_log()
        self.set_interval(0.1, self.update_log)

    def update_log(self) -> None:
        lines = self.bg_task.output
        if len(lines) > self.printed_count:
            for i in range(self.printed_count, len(lines)):
                raw_line = lines[i].rstrip("\r\n")
                self.log_widget.write(raw_line)
            self.printed_count = len(lines)

    def action_back(self) -> None:
        self.dismiss()


class TasksListScreen(ModalScreen[None]):
    """Modal screen with background tasks list"""
    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "close", "Close Manager"),
        ("k", "kill_task", "Kill Task"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("### **Background Tasks Manager**", classes="modal-markdown")
            yield OptionList(id="tasks-option-list")
            yield Label("enter: view output • k: kill task • esc: close", id="modal-hint")

    def on_mount(self) -> None:
        self._ensure_mock_tasks()
        self.update_tasks_list()
        self.query_one("#tasks-option-list", OptionList).focus()
        self.set_interval(0.5, self.update_tasks_list)

    def _ensure_mock_tasks(self) -> None:
        if not self.app.background_tasks:
            from core.background_task import BackgroundTask
            mock1 = BackgroundTask("bash_mock1", "end=$((SECONDS + 600)); while [ $SECONDS -lt $end ]; do echo \"tick\"; sleep 1; done", None)
            mock1.is_running = True
            mock1.output = ["tick 00:01:00\n", "tick 00:01:01\n"]
            mock2 = BackgroundTask("bash_mock2", "uv run ruff check .", None)
            mock2.is_running = False
            mock2.output = ["All checks passed!\n"]
            self.app.background_tasks.append(mock1)
            self.app.background_tasks.append(mock2)

    def update_tasks_list(self) -> None:
        if not self.is_mounted:
            return
        opt_list = self.query_one("#tasks-option-list", OptionList)
        current_highlighted = opt_list.highlighted

        tasks = getattr(self.app, "background_tasks", [])
        opt_list.clear_options()
        if not tasks:
            opt_list.add_option(Text("No active background tasks.", style=THEME_MUTED))
            return

        for t in tasks:
            cmd = t.command
            if len(cmd) > 38:
                cmd = cmd[:35] + "..."
            status_str = "running" if t.is_running else "finished"
            status_style = THEME_PRIMARY if t.is_running else THEME_MUTED

            opt_text = Text()
            opt_text.append(cmd)
            opt_text.append(" | ")
            opt_text.append(status_str, style=status_style)
            opt_list.add_option(opt_text)

        if current_highlighted is not None and current_highlighted < len(tasks):
            opt_list.highlighted = current_highlighted
        else:
            opt_list.highlighted = 0

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_index is not None and event.option_index < len(self.app.background_tasks):
            task = self.app.background_tasks[event.option_index]
            if hasattr(task, "async_task"):
                from widgets.screens.subagent_screen import SubagentViewScreen
                self.app.push_screen(SubagentViewScreen(task.task_id))
            else:
                self.app.push_screen(TaskConsoleScreen(task))

    async def action_kill_task(self) -> None:
        opt_list = self.query_one("#tasks-option-list", OptionList)
        idx = opt_list.highlighted
        if idx is not None and idx < len(self.app.background_tasks):
            task = self.app.background_tasks[idx]
            if task.is_running:
                await task.kill()
                self.app.notify(f"Task {task.task_id} terminated.")
                if not task.is_background:
                    from tools.context import ToolContext
                    out = task.get_formatted_output()
                    msg = (
                        f"[System Notification] Background task '{task.command}' (ID: {task.task_id}) was killed by user.\n"
                        f"<task_result>\n{out.strip() or '[Task terminated by user]'}\n</task_result>"
                    )
                    ToolContext(self.app).trigger_ai_response(msg)
                self.update_tasks_list()
            else:
                self.app.notify("Task is already finished.", severity="warning")

    def action_close(self) -> None:
        self.dismiss()
