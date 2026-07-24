from typing import List

from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Markdown, OptionList

from core.config import THEME_MUTED, THEME_PRIMARY
from core.subagent_registry import SubagentDefinition, SubagentRegistry
from core.subagent_tracker import SubagentSessionData, SubagentTracker
from widgets.screens.subagent_screen import SubagentViewScreen


class TemplateDetailScreen(ModalScreen[None]):
    """Modal screen displaying full definition, tools, and description of a subagent template"""
    BINDINGS = [("escape", "cancel", "Back")]

    def __init__(self, definition: SubagentDefinition):
        super().__init__()
        self.defn = definition

    def compose(self) -> ComposeResult:
        source_tag = self.defn.source.upper()
        header_md = f"### **Subagent Template: {self.defn.name}** (`[{source_tag}]`)\n\n"
        if self.defn.description:
            header_md += f"**Description:** *{self.defn.description}*\n\n"
        if self.defn.tools:
            tools_str = ", ".join(f"`{t}`" for t in self.defn.tools)
            header_md += f"**Tools:** {tools_str}\n\n"
        if self.defn.model:
            header_md += f"**Model:** `{self.defn.model}`\n\n"
        header_md += f"---\n\n### **System Prompt:**\n```\n{self.defn.system_prompt}\n```"

        with Vertical(id="modal-dialog"):
            yield Markdown(header_md, classes="modal-markdown")
            yield Label("esc: back to templates list", id="modal-hint")

    def action_cancel(self) -> None:
        self.dismiss(None)


class SubagentsScreen(ModalScreen[None]):
    """2-Tab Modal screen: Tab 0 = Active Tasks (original SubagentsListScreen), Tab 1 = Subagent Templates"""

    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "cancel", "Close"),
        ("k", "kill_subagent", "Kill Subagent"),
    ]

    def __init__(self):
        super().__init__()
        self.st = SubagentTracker.get_instance()
        self.sr = SubagentRegistry.get_instance()
        self.active_tab = 0  # 0: Active Tasks, 1: Templates
        self.sessions: List[SubagentSessionData] = []
        self.templates: List[SubagentDefinition] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown(self._get_header_title(), id="subagents-title", classes="modal-markdown")
            yield OptionList(id="subagents-option-list")
            yield Label(self._get_hint_text(), id="subagents-hint")

    def _get_header_title(self) -> str:
        if self.active_tab == 0:
            return "### **[ Active Tasks ]** &nbsp;&nbsp;&nbsp;&nbsp; Subagent Templates"
        else:
            return "### &nbsp;&nbsp; Active Tasks &nbsp;&nbsp;&nbsp;&nbsp; **[ Subagent Templates ]**"

    def _get_hint_text(self) -> str:
        if self.active_tab == 0:
            return "enter: watch/view • k: kill • ←/→: switch tab • esc: close • ↑/↓: navigate"
        else:
            return "enter: template details • ←/→: switch tab • esc: close • ↑/↓: navigate"

    def on_mount(self) -> None:
        self.refresh_tab()

    def refresh_tab(self) -> None:
        title_md = self.query_one("#subagents-title", Markdown)
        title_md.update(self._get_header_title())

        hint_label = self.query_one("#subagents-hint", Label)
        hint_label.update(self._get_hint_text())

        opt_list = self.query_one("#subagents-option-list", OptionList)
        opt_list.clear_options()

        if self.active_tab == 0:
            try:
                curr_session_id = getattr(self.app, "current_session_id", None)
            except Exception:
                curr_session_id = None

            self.sessions = self.st.get_sessions_for_session(curr_session_id)

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
        else:
            defs_dict = self.sr.list_definitions()
            self.templates = list(defs_dict.values())
            if not self.templates:
                opt_list.add_option("*No subagent templates registered*")
            else:
                for t in self.templates:
                    source_tag = rf"\[{t.source.upper()}]"
                    opt_list.add_option(f"{source_tag} {t.name}")

        if opt_list.option_count > 0:
            opt_list.highlighted = 0
        opt_list.focus()

    def _on_key(self, event: events.Key) -> None:
        if event.key in ("left", "right", "tab", "backtab"):
            self.active_tab = 1 if self.active_tab == 0 else 0
            self.refresh_tab()
            event.prevent_default()
            event.stop()
            return
        super()._on_key(event)

    def action_cancel(self) -> None:
        self.dismiss(None)

    async def action_kill_subagent(self) -> None:
        if self.active_tab == 0 and self.sessions:
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
                    self.refresh_tab()
                else:
                    if self.app:
                        self.app.notify(f"Subagent is already {sess.status}.", severity="warning")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if self.active_tab == 0:
            if 0 <= event.option_index < len(self.sessions):
                target_sess = self.sessions[event.option_index]
                self.app.push_screen(SubagentViewScreen(target_sess.task_id))
        else:
            if 0 <= event.option_index < len(self.templates):
                target_defn = self.templates[event.option_index]

                def on_tmpl_close(_: None) -> None:
                    opt_list = self.query_one("#subagents-option-list", OptionList)
                    opt_list.focus()
                    opt_list.highlighted = event.option_index

                self.app.push_screen(TemplateDetailScreen(target_defn), callback=on_tmpl_close)
