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
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def action_quit_app(self) -> None:
        self.app.exit()

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("### **Background Tasks Manager**", classes="modal-markdown")
            yield OptionList(id="tasks-option-list")
            yield Label("enter: view output • k: kill task • esc: close", id="modal-hint")

    def on_mount(self) -> None:
        self._last_signatures = None
        self.update_tasks_list()
        self.query_one("#tasks-option-list", OptionList).focus()
        self.set_interval(0.5, self.update_tasks_list)

    def update_tasks_list(self) -> None:
        if not self.is_mounted:
            return
        tasks = getattr(self.app, "background_tasks", [])
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
