from typing import List

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label, Markdown, OptionList

from core.config import THEME_MUTED
from core.subagent_tracker import SubagentSessionData, SubagentTracker
from widgets.screens.subagent_screen import SubagentViewScreen


class SubagentsScreen(ModalScreen[None]):
    """Modal subagents list screen (/subagents). Preserved for backwards compatibility."""

    AUTO_FOCUS = "#subagents-option-list"
    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("k", "kill_subagent", "Kill Subagent"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def __init__(self):
        super().__init__()
        self.st = SubagentTracker.get_instance()
        self.sessions: List[SubagentSessionData] = []
        self.filtered_sessions: List[SubagentSessionData] = []
        self.search_query = ""

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("### **Active Subagent Tasks**", id="subagents-title", classes="modal-markdown modal-markdown-centered")
            yield Input(placeholder="Search subagents...", id="modal-search-input")
            yield OptionList(id="subagents-option-list")
            yield Label("enter: view details • k: kill • esc: cancel", id="modal-hint")

    def on_mount(self) -> None:
        self.refresh_list()
        try:
            self.query_one("#modal-search-input", Input).focus()
        except Exception:
            pass

    def refresh_list(self) -> None:
        self.st._load_all_sessions()
        curr_session_id = None
        try:
            curr_session_id = getattr(self.app, "current_session_id", None)
        except Exception:
            pass

        if curr_session_id:
            self.sessions = self.st.get_sessions_for_session(curr_session_id)
        else:
            self.sessions = self.st.get_sessions_for_session(None)

        if not self.sessions and curr_session_id:
            self.sessions = self.st.get_sessions_for_session(None)

        opt_list = self.query_one("#subagents-option-list", OptionList)
        opt_list.clear_options()

        if self.sessions:
            self.sessions = sorted(self.sessions, key=lambda s: getattr(s, "status", "") != "running")

        q = self.search_query.strip().lower()
        if not q:
            self.filtered_sessions = list(self.sessions)
        else:
            self.filtered_sessions = [
                s for s in self.sessions
                if q in (s.description or "").lower()
                or q in (s.prompt or "").lower()
                or q in (s.task_id or "").lower()
                or q in (getattr(s, "subagent_type", "") or "").lower()
            ]

        if not self.filtered_sessions:
            if not self.sessions:
                opt_list.add_option(Text("No subagents registered for this session.", style=THEME_MUTED))
            else:
                opt_list.add_option(Text("No matching subagents found.", style=THEME_MUTED))
        else:
            for sess in self.filtered_sessions:
                st = (sess.status or "unknown").upper()
                status_tag = f"\\[{st}]"

                desc = sess.description or sess.prompt or sess.task_id
                if len(desc) > 35:
                    desc = desc[:32] + "..."

                opt_list.add_option(f"{status_tag} {desc}")

        if opt_list.option_count > 0:
            opt_list.highlighted = 0

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "modal-search-input":
            self.search_query = event.value
            self.refresh_list()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "modal-search-input":
            opt_list = self.query_one("#subagents-option-list", OptionList)
            idx = opt_list.highlighted
            if idx is not None and 0 <= idx < len(self.filtered_sessions):
                target_sess = self.filtered_sessions[idx]
                self.app.push_screen(SubagentViewScreen(target_sess.task_id))

    def _on_key(self, event: events.Key) -> None:
        if event.key in ("down", "up"):
            try:
                search_input = self.query_one("#modal-search-input", Input)
                if search_input.has_focus:
                    opt_list = self.query_one("#subagents-option-list", OptionList)
                    if opt_list.highlighted is None and self.filtered_sessions:
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

    def action_cancel(self) -> None:
        self.dismiss(None)

    async def action_kill_subagent(self) -> None:
        if self.filtered_sessions:
            opt_list = self.query_one("#subagents-option-list", OptionList)
            idx = opt_list.highlighted
            if idx is not None and 0 <= idx < len(self.filtered_sessions):
                sess = self.filtered_sessions[idx]
                if sess.status == "running":
                    if sess.async_task and not sess.async_task.done():
                        try:
                            sess.async_task.cancel()
                        except Exception:
                            pass
                    sess.finish("cancelled", "Terminated from /subagents menu")
                    self.refresh_list()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.filtered_sessions):
            target_sess = self.filtered_sessions[event.option_index]
            self.app.push_screen(SubagentViewScreen(target_sess.task_id))
