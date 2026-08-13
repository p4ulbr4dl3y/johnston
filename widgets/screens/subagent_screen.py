import asyncio

from textual.app import ComposeResult
from textual.widgets import Markdown

from widgets.chat_container import ChatView
from widgets.screens.base_modal import BaseModalScreen
from widgets.screens.constants import MODAL_MARKDOWN, MODAL_MARKDOWN_CENTERED


class SubagentViewScreen(BaseModalScreen[None]):
    """Fullscreen subagent chat view reusing the same ChatView widget as the main chat.

    Renders the subagent's persisted history with ``ChatView.restore_messages`` and
    streams live events via ``ChatView.append_event`` — no duplicated message
    rendering anywhere. Read-only: no input panel.
    """

    BINDINGS = [
        ("escape", "close", "Close Screen"),
    ]

    def __init__(self, session_id_or_desc: str):
        super().__init__()
        self.session_id_or_desc = session_id_or_desc
        self.session = None
        self.event_queue = asyncio.Queue()
        self.queue_task = None

    def compose(self) -> ComposeResult:
        # Fullscreen chat, framed like the main agent view (no modal chrome).
        yield Markdown("### **Subagent**", classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}")
        yield ChatView(id="subagent-chat-view")

    def on_mount(self) -> None:
        chat_view = self.query_one("#subagent-chat-view", ChatView)
        chat_view.focus()

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

        self.run_worker(self._load_history_session())

    async def _load_history_session(self) -> None:
        chat_view = self.query_one("#subagent-chat-view", ChatView)
        chat_view.loading = True
        chat_view.reset_stream_state()

        for child in list(chat_view.children):
            child.remove()

        if self.session:
            history_events = list(self.session.messages)
            has_user_msg = any(isinstance(e, dict) and e.get("type") == "user" for e in history_events)
            if not has_user_msg and getattr(self.session, "prompt", None):
                await chat_view.add_user_message(self.session.prompt, animate=False)
            await chat_view.restore_messages(history_events, loading=False)

        await asyncio.sleep(0.1)
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
        chat_view = self.query_one("#subagent-chat-view", ChatView)
        while True:
            try:
                evt = await self.event_queue.get()
                try:
                    await chat_view.append_event(evt)
                finally:
                    self.event_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    def action_close(self) -> None:
        self.dismiss()
