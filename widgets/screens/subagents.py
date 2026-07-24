from typing import List

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Markdown, OptionList

from core.subagent_registry import SubagentDefinition, SubagentRegistry
from core.subagent_tracker import SubagentSessionData, SubagentTracker


class SubagentDetailScreen(ModalScreen[None]):
    """Modal screen displaying detailed log of a subagent session"""
    BINDINGS = [("escape", "cancel", "Back")]

    def __init__(self, session_data: SubagentSessionData):
        super().__init__()
        self.sess = session_data

    def compose(self) -> ComposeResult:
        status_str = self.sess.status.upper()
        type_str = self.sess.subagent_type.upper()
        header_md = f"### **Subagent Task: {self.sess.description}** (`[{status_str}] [{type_str}]`)\n\n"
        header_md += f"**ID:** `{self.sess.task_id}`\n\n"
        header_md += f"**Prompt:** {self.sess.prompt}\n\n---\n\n### **Events & Logs:**\n"

        logs = []
        for evt in self.sess.events:
            etype = evt.get("type", "")
            if etype in ("bot_delta", "bot_chunk", "thinking_delta"):
                continue
            if etype == "bot_text":
                logs.append(f"**Assistant:**\n{evt.get('content', '')}")
            elif etype == "tool_start":
                logs.append(f"**Tool Invoked:** `{evt.get('name')}`({evt.get('args')})")
            elif etype == "tool_result":
                logs.append(f"**Tool Result:**\n```\n{evt.get('result', '')[:300]}\n```")
            elif etype == "status_change":
                logs.append(f"**Status Change:** `{evt.get('status')}` {evt.get('error', '')}")

        body_md = header_md + ("\n\n".join(logs) if logs else "*No events recorded yet.*")

        with Vertical(id="modal-dialog"):
            yield Markdown(body_md, classes="modal-markdown")
            yield Label("esc: back to subagents list", id="modal-hint")

    def action_cancel(self) -> None:
        self.dismiss(None)


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
    """2-Tab Modal screen for Subagents: [ Tasks ] & [ Templates ] (Single-line list view)"""

    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "cancel", "Close"),
    ]

    def __init__(self):
        super().__init__()
        self.st = SubagentTracker.get_instance()
        self.sr = SubagentRegistry.get_instance()
        self.active_tab = 0  # 0: Tasks, 1: Templates
        self.sessions: List[SubagentSessionData] = []
        self.templates: List[SubagentDefinition] = []

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown(self._get_header_title(), id="subagents-title", classes="modal-markdown")
            yield OptionList(id="subagents-option-list")
            yield Label("←/→: switch tab • enter: view details • esc: close • ↑/↓: navigate", id="modal-hint")

    def _get_header_title(self) -> str:
        if self.active_tab == 0:
            return "### **[ Active Tasks ]** &nbsp;&nbsp;&nbsp;&nbsp; Subagent Templates"
        else:
            return "### &nbsp;&nbsp; Active Tasks &nbsp;&nbsp;&nbsp;&nbsp; **[ Subagent Templates ]**"

    def on_mount(self) -> None:
        self.refresh_tab()

    def refresh_tab(self) -> None:
        title_md = self.query_one("#subagents-title", Markdown)
        title_md.update(self._get_header_title())

        opt_list = self.query_one("#subagents-option-list", OptionList)
        opt_list.clear_options()

        if self.active_tab == 0:
            self.sessions = self.st.get_sessions_for_session()
            if not self.sessions:
                opt_list.add_option("*No subagent tasks spawned yet*")
            else:
                for s in reversed(self.sessions):
                    status_upper = s.status.upper()
                    if status_upper in ("RUNNING", "ACTIVE"):
                        status_tag = r"\[RUNNING]"
                    elif status_upper in ("COMPLETED", "DONE"):
                        status_tag = r"\[DONE]"
                    else:
                        status_tag = rf"\[{status_upper}]"

                    type_tag = rf"\[{s.subagent_type.upper()}]"
                    desc = s.description or s.prompt[:35]
                    opt_list.add_option(f"{status_tag} {type_tag} {desc} (id: {s.task_id[:8]})")
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

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if self.active_tab == 0:
            rev_sessions = list(reversed(self.sessions))
            if 0 <= event.option_index < len(rev_sessions):
                target_sess = rev_sessions[event.option_index]

                def on_detail_close(_: None) -> None:
                    opt_list = self.query_one("#subagents-option-list", OptionList)
                    opt_list.focus()
                    opt_list.highlighted = event.option_index

                self.app.push_screen(SubagentDetailScreen(target_sess), callback=on_detail_close)
        else:
            if 0 <= event.option_index < len(self.templates):
                target_defn = self.templates[event.option_index]

                def on_tmpl_close(_: None) -> None:
                    opt_list = self.query_one("#subagents-option-list", OptionList)
                    opt_list.focus()
                    opt_list.highlighted = event.option_index

                self.app.push_screen(TemplateDetailScreen(target_defn), callback=on_tmpl_close)
