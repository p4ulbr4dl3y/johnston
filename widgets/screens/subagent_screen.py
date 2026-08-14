import asyncio

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Label

from widgets.chat_view import ChatView
from widgets.status_footer import SubagentStatusFooter


class SubagentInfoLabel(Label):
    """Header label for the subagent screen: not selectable, dimmed esc hint."""

    ALLOW_SELECT = False
    can_focus = False


class SubagentViewScreen(Screen[None]):
    """Full-screen view of a subagent's chat without input panel or status footer."""

    BINDINGS = [
        ("escape", "close", "Close Screen"),
    ]

    def __init__(self, session_id_or_desc: str):
        super().__init__()
        self.session_id_or_desc = session_id_or_desc
        self.session = None
        self.thinking_widget = None
        self.current_tool_widget = None
        self.bot_msg = None
        self.event_queue = asyncio.Queue()
        self.queue_task = None

    def compose(self) -> ComposeResult:
        with Vertical(id="subagent-container"):
            yield ChatView(id="subagent-chat-view", show_welcome=False)
            yield SubagentInfoLabel("", id="subagent-info")
            yield SubagentStatusFooter(id="subagent-status-footer")

    def on_mount(self) -> None:
        chat_view = self.query_one("#subagent-chat-view", ChatView)
        chat_view.focus()
        chat_view.clear_welcome()
        self._update_info_label(self.session_id_or_desc)

        store = getattr(self.app, "sm", None) if self.app else None
        if store is None:
            from core.session_manager import SessionStore

            store = SessionStore.get_instance()

        curr_session_id = getattr(self.app, "current_session_id", None) if self.app else None
        self.session = store.find_session_by_description_or_id(self.session_id_or_desc, parent_id=curr_session_id)
        if not self.session:
            self.session = store.find_session_by_description_or_id(self.session_id_or_desc)

        if not self.session:

            async def _no_sess():
                bm = await chat_view.add_bot_message()
                bm.content = f"Subagent `{self.session_id_or_desc}` session details not found."

            self.run_worker(_no_sess())
            return

        if getattr(self.session, "description", None):
            self._update_info_label(self.session.description)

        footer = self.query_one("#subagent-status-footer", SubagentStatusFooter)
        footer.update_session(self.session)

        # Keep the footer live while the subagent streams (tokens, spinner).
        # Stop any stale interval from a previous mount before re-arming.
        if getattr(self, "_footer_refresh", None) is not None:
            try:
                self._footer_refresh.stop()
            except Exception:
                pass
        self._footer_refresh = self.set_interval(1.0, lambda: footer.update_session(self.session))

        self._history_worker = self.run_worker(self._load_history_session())

    def _update_info_label(self, text: str) -> None:
        from rich.table import Table

        grid = Table.grid(expand=True)
        grid.add_column(justify="left")
        grid.add_column(justify="right")
        grid.add_row(text, "[dim]esc: cancel[/dim]")
        label = self.query_one("#subagent-info", SubagentInfoLabel)
        label._raw_text = text
        label.update(grid)

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
            history_events = list(self.session.messages)
            has_user_msg = any(isinstance(e, dict) and e.get("type") == "user" for e in history_events)
            if not has_user_msg and getattr(self.session, "prompt", None):
                await chat_view.add_user_message(self.session.prompt, animate=False)

            for evt in history_events:
                await self._render_event(evt, animate=False)

        if self.bot_msg:
            try:
                await self.bot_msg.finalize_stream()
            except Exception:
                pass
            self.bot_msg = None

        await asyncio.sleep(0.1)
        chat_view._is_loading_session = False
        chat_view.loading = False
        try:
            chat_view.call_after_refresh(chat_view.scroll_end, animate=False)
        except Exception:
            pass

        if not self.is_mounted:
            return

        if not self.queue_task or self.queue_task.done():
            self.queue_task = asyncio.create_task(self._process_queue())

        if self.session:
            self.session.remove_listener(self._on_live_event)
            self.session.add_listener(self._on_live_event)

    def on_unmount(self) -> None:
        if getattr(self, "_footer_refresh", None) is not None:
            try:
                self._footer_refresh.stop()
            except Exception:
                pass
            self._footer_refresh = None
        if getattr(self, "_history_worker", None) is not None:
            try:
                self._history_worker.cancel()
            except Exception:
                pass
            self._history_worker = None
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
        elif etype == "thinking":
            txt = evt.get("text", "")
            if self.thinking_widget is None:
                self.thinking_widget = await chat_view.add_thinking_widget(txt, animate=animate)
            else:
                self.thinking_widget.update_thinking(txt)
            if evt.get("duration") is not None:
                self.thinking_widget.finish_thinking(evt.get("duration", 0.0), txt)
                self.thinking_widget = None
        elif etype == "tool":
            if "result_text" in evt and not evt.get("tool_type"):
                if self.current_tool_widget:
                    self.current_tool_widget.set_result(evt.get("result_text", ""))
            else:
                if self.bot_msg:
                    if not self.bot_msg.content.strip():
                        try:
                            self.bot_msg.remove()
                        except Exception:
                            pass
                    else:
                        self.bot_msg.flush_pending_stream()
                        await self.bot_msg.finalize_stream()
                    self.bot_msg = None
                self.current_tool_widget = await chat_view.add_tool_call(
                    evt.get("tool_type", ""),
                    evt.get("target", ""),
                    result_text=evt.get("result_text", ""),
                    args=evt.get("args", {}),
                    animate=animate,
                )
        elif etype == "bot":
            txt = evt.get("text", "")
            if txt:
                if self.bot_msg is None:
                    self.bot_msg = await chat_view.add_bot_message(animate=animate)
                if evt.get("final") or not animate:
                    await self.bot_msg.set_final_content(txt)
                    self.bot_msg = None
                else:
                    self.bot_msg.set_stream_content(txt)
        elif etype == "bot_reset":
            if self.bot_msg:
                try:
                    await self.bot_msg.reset_stream()
                except Exception:
                    pass
        elif etype == "event_divider":
            await chat_view.add_event_divider(evt.get("text", "Session Compacted"), animate=animate)
        elif etype == "status_change":
            pass

    def action_close(self) -> None:
        self.dismiss()

    def action_quit_app(self) -> None:
        self.app.exit()
