from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Markdown, OptionList

from core.config import THEME_MUTED, THEME_PRIMARY
from core.subagent_tracker import SubagentTracker
from widgets.screens.subagent_screen import SubagentViewScreen


class SubagentsListScreen(ModalScreen[None]):
    """Modal screen displaying list of subagents for current chat session"""

    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "close", "Close Screen"),
        ("k", "kill_subagent", "Kill Subagent"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("### **Subagents Manager**", classes="modal-markdown")
            yield OptionList(id="subagents-option-list")
            yield Label("enter: watch / view • k: kill subagent • esc: close", id="modal-hint")

    def on_mount(self) -> None:
        self.update_subagents_list()
        self.query_one("#subagents-option-list", OptionList).focus()
        self.set_interval(0.5, self.update_subagents_list)

    def _get_target_sessions(self):
        tracker = SubagentTracker.get_instance()
        try:
            curr_session_id = getattr(self.app, "current_session_id", None)
        except Exception:
            curr_session_id = None
        return tracker.get_sessions_for_session(curr_session_id)

    def update_subagents_list(self) -> None:
        if not self.is_mounted:
            return
        opt_list = self.query_one("#subagents-option-list", OptionList)
        current_highlighted = opt_list.highlighted
        sessions = self._get_target_sessions()

        opt_list.clear_options()
        for sess in sessions:
            st = sess.status.lower()
            if st == "running":
                status = f"[{THEME_PRIMARY}]running[/]"
            elif st == "completed":
                status = f"[{THEME_MUTED}]completed[/]"
            else:
                status = f"[{THEME_MUTED}]{st}[/]"

            desc = sess.description or sess.prompt or sess.task_id
            if len(desc) > 38:
                desc = desc[:35] + "..."
            opt_list.add_option(f"{desc} | {status}")

        if sessions:
            if current_highlighted is not None and current_highlighted < len(sessions):
                opt_list.highlighted = current_highlighted
            else:
                opt_list.highlighted = 0

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        sessions = self._get_target_sessions()
        if event.option_index is not None and event.option_index < len(sessions):
            sess = sessions[event.option_index]
            self.app.push_screen(SubagentViewScreen(sess.task_id))

    async def action_kill_subagent(self) -> None:
        opt_list = self.query_one("#subagents-option-list", OptionList)
        idx = opt_list.highlighted
        sessions = self._get_target_sessions()
        if idx is not None and idx < len(sessions):
            sess = sessions[idx]
            if sess.status == "running":
                if sess.async_task and not sess.async_task.done():
                    try:
                        sess.async_task.cancel()
                    except Exception:
                        pass
                sess.finish("cancelled", "Terminated from /subagents menu")
                if self.app:
                    self.app.notify(f"Subagent {sess.task_id} terminated.")
                self.update_subagents_list()
            else:
                if self.app:
                    self.app.notify(f"Subagent is already {sess.status}.", severity="warning")

    def action_close(self) -> None:
        self.dismiss()
