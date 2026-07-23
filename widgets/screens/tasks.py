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
            yield Markdown(f"### **Console Output: `{self.bg_task.command}`**")
            yield RichLog(id="console-log", highlight=True, markup=True)
            yield Label("Press Escape to return to tasks menu", id="modal-hint")

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
            yield Markdown("### **Background Tasks Manager**")
            yield OptionList(id="tasks-option-list")
            yield Label("Enter: View Output | K: Kill Task | Escape: Close", id="modal-hint")

    def on_mount(self) -> None:
        self.update_tasks_list()
        self.query_one("#tasks-option-list", OptionList).focus()
        self.set_interval(0.5, self.update_tasks_list)

    def update_tasks_list(self) -> None:
        if not self.is_mounted:
            return
        opt_list = self.query_one("#tasks-option-list", OptionList)
        current_highlighted = opt_list.highlighted

        opt_list.clear_options()
        for t in self.app.background_tasks:
            status = f"[{THEME_PRIMARY}]Running[/{THEME_PRIMARY}]" if t.is_running else f"[{THEME_MUTED}]Finished[/{THEME_MUTED}]"
            opt_list.add_option(f"{t.task_id} | {status} | {t.command}")

        if current_highlighted is not None and current_highlighted < len(self.app.background_tasks):
            opt_list.highlighted = current_highlighted

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_index is not None and event.option_index < len(self.app.background_tasks):
            task = self.app.background_tasks[event.option_index]
            self.app.push_screen(TaskConsoleScreen(task))

    async def action_kill_task(self) -> None:
        opt_list = self.query_one("#tasks-option-list", OptionList)
        idx = opt_list.highlighted
        if idx is not None and idx < len(self.app.background_tasks):
            task = self.app.background_tasks[idx]
            if task.is_running:
                await task.kill()
                self.app.notify(f"Task {task.task_id} terminated.")
                self.update_tasks_list()
            else:
                self.app.notify("Task is already finished.", severity="warning")

    def action_close(self) -> None:
        self.dismiss()
