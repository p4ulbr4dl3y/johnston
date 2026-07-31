from typing import List

from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Markdown, OptionList

from core.config import THEME_MUTED, THEME_PRIMARY
from core.subagent_tracker import SubagentSessionData, SubagentTracker
from widgets.screens.subagent_screen import SubagentViewScreen


class SubagentsScreen(ModalScreen[None]):
    """Modal screen displaying active subagent tasks with options to watch or kill."""

    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("k", "kill_subagent", "Kill Subagent"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def action_quit_app(self) -> None:
        self.app.exit()

    def __init__(self):
        super().__init__()
        self.st = SubagentTracker.get_instance()
        self.sessions: List[SubagentSessionData] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("### **Active Subagent Tasks**", id="subagents-title", classes="modal-markdown")
            yield OptionList(id="subagents-option-list")
            yield Label("enter: view details • k: kill • esc: close", id="modal-hint")

    def on_mount(self) -> None:
        self.refresh_list()

    def refresh_list(self) -> None:
        self.st._load_all_sessions()
        opt_list = self.query_one("#subagents-option-list", OptionList)
        opt_list.clear_options()

        try:
            curr_session_id = getattr(self.app, "current_session_id", None)
        except Exception:
            curr_session_id = None

        self.sessions = self.st.get_sessions_for_session(curr_session_id)
        if not self.sessions and curr_session_id:
            self.sessions = self.st.get_sessions_for_session(None)

        if not self.sessions:
            opt_list.add_option(Text("No subagents registered for this session.", style=THEME_MUTED))
        else:
            for sess in self.sessions:
                st = sess.status.lower()
                status_style = THEME_PRIMARY if st == "running" else THEME_MUTED

                desc = sess.description or sess.prompt or sess.task_id
                if len(desc) > 38:
                    desc = desc[:35] + "..."

                opt_text = Text()
                opt_text.append(desc)
                opt_text.append(" | ")
                opt_text.append(st, style=status_style)
                opt_list.add_option(opt_text)

        if opt_list.option_count > 0:
            opt_list.highlighted = 0
        opt_list.focus()

    def action_cancel(self) -> None:
        self.dismiss(None)

    async def action_kill_subagent(self) -> None:
        if self.sessions:
            opt_list = self.query_one("#subagents-option-list", OptionList)
            idx = opt_list.highlighted
            if idx is not None and 0 <= idx < len(self.sessions):
                sess = self.sessions[idx]
                if sess.status == "running":
                    if sess.async_task and not sess.async_task.done():
                        try:
                            sess.async_task.cancel()
                        except Exception:
                            pass
                    sess.finish("cancelled", "Terminated from /subagents menu")
                    if self.app:
                        self.app.notify(f"Subagent {sess.task_id} terminated.")
                    self.refresh_list()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.sessions):
            target_sess = self.sessions[event.option_index]
            self.app.push_screen(SubagentViewScreen(target_sess.task_id))

