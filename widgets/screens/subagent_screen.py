import asyncio

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Markdown

from core.subagent_tracker import SubagentTracker
from widgets.chat_view import ChatView


class SubagentViewScreen(ModalScreen[None]):
    """Modal screen for watching subagent execution in a full chat window without input panel."""

    ALLOW_SELECT = False
    BINDINGS = [
        ("escape", "close", "Close Screen"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ]

    def action_quit_app(self) -> None:
        self.app.exit()

    def __init__(self, task_id_or_desc: str):
        super().__init__()
        self.task_id_or_desc = task_id_or_desc
        self.session = SubagentTracker.get_instance().find_session_by_description_or_id(task_id_or_desc)
        self.thinking_widget = None
        self.current_tool_widget = None
        self.bot_msg = None
        self.event_queue = asyncio.Queue()
        self.queue_task = None

    def compose(self) -> ComposeResult:
        desc = self.session.description if self.session else self.task_id_or_desc
        status = self.session.status.lower() if self.session else "not found"
        with Vertical(id="modal-dialog"):
            yield Markdown(f"### **Subagent:** `{desc}` • {status}", classes="modal-markdown")
            yield ChatView(id="subagent-chat-view", show_welcome=False)
            yield Label("esc: close window", id="modal-hint")

    def on_mount(self) -> None:
        chat_view = self.query_one("#subagent-chat-view", ChatView)
        chat_view.focus()
        chat_view.clear_welcome()

        if not self.session:
            curr_session_id = getattr(self.app, "current_session_id", None) if self.app else None
            self.session = SubagentTracker.get_instance().find_session_by_description_or_id(
                self.task_id_or_desc, session_id=curr_session_id
            )

        if not self.session:
            async def _no_sess():
                bm = await chat_view.add_bot_message()
                bm.content = f"Subagent `{self.task_id_or_desc}` session details not found."
            self.run_worker(_no_sess())
            return

        try:
            desc = self.session.description or self.task_id_or_desc
            status = self.session.status.lower()
            title_md = self.query_one(".modal-markdown", Markdown)
            title_md.update(f"### **Subagent:** `{desc}` • {status}")
        except Exception:
            pass

        self.run_worker(self._load_history_session())

    async def _load_history_session(self) -> None:
        chat_view = self.query_one("#subagent-chat-view", ChatView)
        chat_view.loading = True
        chat_view._is_loading_session = True

        for child in list(chat_view.children):
            child.remove()
        self.thinking_widget = None
        self.current_tool_widget = None
        self.bot_msg = None

        if self.session:
            history_events = list(self.session.events)
            for evt in history_events:
                await self._render_event(evt, animate=False)

        await asyncio.sleep(0.1)
        chat_view._is_loading_session = False
        chat_view.loading = False
        try:
            chat_view.call_after_refresh(chat_view.scroll_end, animate=False)
        except Exception:
            pass

        if not self.queue_task or self.queue_task.done():
            self.queue_task = asyncio.create_task(self._process_queue())

        if self.session:
            self.session.remove_listener(self._on_live_event)
            self.session.add_listener(self._on_live_event)

    def on_unmount(self) -> None:
        if self.queue_task and not self.queue_task.done():
            self.queue_task.cancel()
        if self.session:
            self.session.remove_listener(self._on_live_event)

    def _on_live_event(self, evt: dict) -> None:
        if self.is_mounted and hasattr(self, "event_queue"):
            self.event_queue.put_nowait(evt)

    async def _process_queue(self) -> None:
        while True:
            try:
                evt = await self.event_queue.get()
                try:
                    await self._render_event(evt)
                finally:
                    self.event_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def _render_event(self, evt: dict, animate: bool = True) -> None:
        chat_view = self.query_one("#subagent-chat-view", ChatView)
        etype = evt.get("type")

        if etype == "user":
            await chat_view.add_user_message(evt.get("text", ""), animate=animate)
        elif etype == "thinking_start":
            self.thinking_widget = await chat_view.add_thinking_widget(evt.get("val1", ""), animate=animate)
        elif etype == "thinking_delta":
            if self.thinking_widget:
                self.thinking_widget.update_thinking(evt.get("val1", ""))
        elif etype == "thinking_end":
            if self.thinking_widget:
                self.thinking_widget.finish_thinking(evt.get("duration", 0.0), evt.get("content", ""))
                self.thinking_widget = None
        elif etype == "tool":
            if self.bot_msg and not self.bot_msg.content.strip():
                try:
                    self.bot_msg.remove()
                except Exception:
                    pass
            self.bot_msg = None
            self.current_tool_widget = await chat_view.add_tool_call(
                evt.get("tool_type", ""), evt.get("target", ""), args=evt.get("args", {}), animate=animate
            )
        elif etype == "tool_result":
            if self.current_tool_widget:
                self.current_tool_widget.set_result(evt.get("result_text", ""))
        elif etype == "bot_delta":
            txt = evt.get("text", "")
            if txt:
                if self.bot_msg is None:
                    self.bot_msg = await chat_view.add_bot_message(animate=animate)
                self.bot_msg.content = txt
        elif etype == "bot_chunk":
            txt = evt.get("text", "")
            if txt:
                if self.bot_msg is None:
                    self.bot_msg = await chat_view.add_bot_message(animate=animate)
                self.bot_msg.content += txt
        elif etype == "bot_text":
            txt = evt.get("text", "")
            if txt:
                if self.bot_msg is None:
                    self.bot_msg = await chat_view.add_bot_message(animate=animate)
                self.bot_msg.content = txt
                self.bot_msg = None
        elif etype == "status_change":
            status = evt.get("status", "").lower()
            try:
                desc = self.session.description if self.session else self.task_id_or_desc
                title_md = self.query_one(".modal-markdown", Markdown)
                title_md.update(f"### **Subagent:** `{desc}` • {status}")
            except Exception:
                pass

    def action_close(self) -> None:
        self.dismiss()
