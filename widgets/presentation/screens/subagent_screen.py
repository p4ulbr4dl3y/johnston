import asyncio

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen

from core.domain.policies.messages import is_ui_visible_user_message
from widgets.presentation.widgets.chat_container import ChatView
from widgets.presentation.widgets.plan_notch import PlanNotch, PlanNotchContainer
from widgets.presentation.widgets.subagent_footer import SubagentStatusFooter
from widgets.utils.key_aliases import expand_bindings


class SubagentViewScreen(ModalScreen[None]):
    """Full-screen view of a subagent's chat without input panel."""

    inherit_bindings = False
    BINDINGS = expand_bindings([
        ("escape", "close", "Close Screen"),
        ("ctrl+k", "kill_subagent", "Kill Subagent"),
        ("ctrl+p", "toggle_plan", "Toggle Plan"),
        ("ctrl+h", "toggle_plan_hidden", "Hide/Show Plan"),
        ("ctrl+o", "toggle_expand", "Toggle Expand"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ])

    def __init__(self, session_id_or_desc: str, from_tasks: bool = False):
        super().__init__()
        self.session_id_or_desc = session_id_or_desc
        self.from_tasks = from_tasks
        self.session = None
        self.thinking_widget = None
        self.current_tool_widget = None
        self.pending_tool_widgets = []
        self.bot_msg = None
        self.event_queue = asyncio.Queue()
        self.queue_task = None

    def compose(self) -> ComposeResult:
        yield PlanNotchContainer(id="plan-notch-container")
        with Vertical(id="subagent-container"):
            yield ChatView(id="subagent-chat-view", show_welcome=False)
            yield SubagentStatusFooter(from_tasks=self.from_tasks, id="subagent-status-footer")

    def action_toggle_plan(self) -> None:
        """Toggle expansion of the top plan notch widget."""
        try:
            notch = self.query_one(PlanNotch)
            if not notch.plan_items:
                self.notify("No active plan", severity="information")
                return
            notch.toggle_expanded()
        except Exception:
            pass

    def action_toggle_plan_hidden(self) -> None:
        """Toggle visibility/hidden state of the top plan notch widget."""
        try:
            notch = self.query_one(PlanNotch)
            notch.toggle_hidden()
        except Exception:
            pass

    def on_mount(self) -> None:
        chat_view = self.query_one("#subagent-chat-view", ChatView)
        chat_view.focus()
        chat_view.clear_welcome()

        store = getattr(self.app, "sm", None) if self.app else None
        if store is None:
            from core.infrastructure.storage.session_store import SessionStore

            store = SessionStore.get_instance()

        curr_session_id = getattr(self.app, "current_session_id", None) if self.app else None
        self.session = store.find_session_by_title_or_id(self.session_id_or_desc, parent_id=curr_session_id)
        if not self.session:
            self.session = store.find_session_by_title_or_id(self.session_id_or_desc)

        if not self.session:

            async def _no_sess():
                bm = await chat_view.add_bot_message()
                bm.content = f"Subagent `{self.session_id_or_desc}` session details not found."

            self.run_worker(_no_sess())
            return

        footer = self.query_one("#subagent-status-footer", SubagentStatusFooter)
        footer.update_session(self.session)

        # Stop any stale interval from a previous mount
        if getattr(self, "_footer_refresh", None) is not None:
            try:
                self._footer_refresh.stop()
            except Exception:
                pass
            self._footer_refresh = None

        self._history_worker = self.run_worker(self._load_history_session())

    def _refresh_chrome(self) -> None:
        try:
            self.query_one("#subagent-status-footer", SubagentStatusFooter).update_session(self.session)
        except Exception:
            pass

    def _get_app(self):
        try:
            return self.app
        except Exception:
            return None

    def _save_expand_state(self) -> None:
        app = self._get_app()
        if not self.session or not app:
            return
        if not hasattr(app, "_subagent_expand_state") or not isinstance(app._subagent_expand_state, dict):
            app._subagent_expand_state = {}
        try:
            chat_view = self.query_one("#subagent-chat-view", ChatView)
            expanded_indices = set()
            for idx, child in enumerate(chat_view.children):
                if getattr(child, "is_expanded", False):
                    expanded_indices.add(idx)
            app._subagent_expand_state[self.session.id] = expanded_indices
        except Exception:
            pass

    async def _load_history_session(self) -> None:
        chat_view = self.query_one("#subagent-chat-view", ChatView)
        chat_view.loading = True
        chat_view._is_loading_session = True
        try:
            from widgets.presentation.widgets.plan_notch import PlanNotch

            self.query_one(PlanNotch).clear_plan()
        except Exception:
            pass

        for child in list(chat_view.children):
            child.remove()
        self.thinking_widget = None
        self.current_tool_widget = None
        self.bot_msg = None

        rendered_count = 0
        is_running = bool(self.session and getattr(self.session, "status", "") == "running")
        app = self._get_app()
        expand_state = set()
        if app and self.session and hasattr(app, "_subagent_expand_state") and isinstance(app._subagent_expand_state, dict):
            expand_state = app._subagent_expand_state.get(self.session.id, set())

        if self.session:
            history_events = list(self.session.messages)
            rendered_count = len(history_events)
            has_user_msg = any(
                isinstance(e, dict) and e.get("type") == "user" and is_ui_visible_user_message(e)
                for e in history_events
            )
            child_offset = 0
            if not has_user_msg and getattr(self.session, "prompt", None):
                await chat_view.add_user_message(self.session.prompt, animate=False)
                child_offset = 1

            for idx, evt in enumerate(history_events):
                is_last_running = is_running and (idx == len(history_events) - 1)
                await self._render_event(
                    evt,
                    animate=is_last_running,
                    is_active=is_last_running,
                )

        for idx, child in enumerate(chat_view.children):
            if idx in expand_state and hasattr(child, "set_expanded"):
                child.set_expanded(True)

        if is_running:
            if self.thinking_widget and hasattr(self.thinking_widget, "set_expanded"):
                self.thinking_widget.set_expanded(True)
            elif self.current_tool_widget and hasattr(self.current_tool_widget, "set_expanded"):
                self.current_tool_widget.set_expanded(True)

        if not is_running and self.bot_msg:
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
            current_msgs = list(self.session.messages)
            if len(current_msgs) > rendered_count:
                for evt in current_msgs[rendered_count:]:
                    self.event_queue.put_nowait(evt)

            has_subsequent_user_msg = False
            for evt in reversed(current_msgs or []):
                if not isinstance(evt, dict):
                    continue
                etype = evt.get("type")
                if etype == "user":
                    has_subsequent_user_msg = True
                elif etype == "tool" and evt.get("tool_type") == "update_plan":
                    args = evt.get("args") or {}
                    if isinstance(args, dict) and args.get("plan"):
                        p_items = [p for p in args.get("plan", []) if isinstance(p, dict)]
                        if p_items and all(p.get("status") == "completed" for p in p_items) and has_subsequent_user_msg:
                            break
                        try:
                            self.query_one(PlanNotch).set_plan(p_items, args.get("explanation", ""))
                        except Exception:
                            pass
                        break
            self._refresh_chrome()

    def on_unmount(self) -> None:
        self._save_expand_state()
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
                    self._refresh_chrome()
                finally:
                    self.event_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def _render_event(
        self,
        evt: dict,
        animate: bool = True,
        is_expanded: bool = False,
        is_active: bool = False,
    ) -> None:
        chat_view = self.query_one("#subagent-chat-view", ChatView)
        etype = evt.get("type")

        if etype == "user":
            if not is_ui_visible_user_message(evt):
                return
            att_count = evt.get("attachments_count", 0)
            if not att_count and evt.get("attachments"):
                att_count = len(evt.get("attachments"))
            await chat_view.add_user_message(
                evt.get("display_text") or evt.get("text", ""),
                animate=animate,
                attachments_count=att_count,
            )
        elif etype == "thinking":
            txt = evt.get("text", "")
            if self.thinking_widget is None:
                self.thinking_widget = await chat_view.add_thinking_widget(txt, animate=animate)
                if is_expanded and hasattr(self.thinking_widget, "is_expandable") and self.thinking_widget.is_expandable():
                    self.thinking_widget.is_expanded = True
            else:
                self.thinking_widget.update_thinking(txt)
            if evt.get("duration") is not None:
                self.thinking_widget.finish_thinking(evt.get("duration", 0.0), txt)
                self.thinking_widget = None
        elif etype == "tool":
            if "result_text" in evt and not evt.get("tool_type"):
                if getattr(self, "pending_tool_widgets", None):
                    w = self.pending_tool_widgets.pop(0)
                    w.set_result(
                        evt.get("result_text", ""),
                        is_error=bool(evt.get("is_error", False)),
                        status=evt.get("status"),
                        returncode=evt.get("returncode"),
                    )
                elif self.current_tool_widget:
                    self.current_tool_widget.set_result(
                        evt.get("result_text", ""),
                        is_error=bool(evt.get("is_error", False)),
                        status=evt.get("status"),
                        returncode=evt.get("returncode"),
                    )
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
                widget = await chat_view.add_tool_call(
                    evt.get("tool_type", ""),
                    evt.get("target", ""),
                    result_text=evt.get("result_text", ""),
                    args=evt.get("args", {}),
                    status=evt.get("status"),
                    returncode=evt.get("returncode"),
                    animate=animate,
                )
                if is_expanded and hasattr(widget, "is_expandable") and widget.is_expandable():
                    widget.is_expanded = True
                self.current_tool_widget = widget
                if animate and evt.get("tool_type") == "update_plan":
                    args = evt.get("args") or {}
                    if isinstance(args, dict) and isinstance(args.get("plan"), list):
                        try:
                            self.query_one(PlanNotch).set_plan(args.get("plan", []), args.get("explanation", ""))
                        except Exception:
                            pass
                if not evt.get("result_text"):
                    if not hasattr(self, "pending_tool_widgets") or self.pending_tool_widgets is None:
                        self.pending_tool_widgets = []
                    self.pending_tool_widgets.append(widget)
        elif etype == "bot":
            txt = evt.get("text", "")
            if not animate and not is_active and not txt.strip():
                return
            if txt:
                if self.bot_msg is None:
                    self.bot_msg = await chat_view.add_bot_message(animate=animate or is_active)
                if evt.get("final") or (not animate and not is_active):
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
        elif etype == "error":
            await chat_view.add_error_message(evt.get("text", "Error"), animate=animate)
        elif etype == "event_divider":
            await chat_view.add_event_divider(evt.get("text", "Session Compacted"), animate=animate)
        elif etype == "status_change":
            pass

    def action_close(self) -> None:
        self.dismiss()

    def action_kill_subagent(self) -> None:
        """Kill the current subagent if running."""
        if self.session and getattr(self.session, "status", "") == "running":
            if getattr(self.session, "async_task", None) and not self.session.async_task.done():
                try:
                    self.session.async_task.cancel()
                except Exception:
                    pass
            if hasattr(self.session, "finish"):
                self.session.finish("cancelled", "Terminated from subagent view")
            self._refresh_chrome()

    def action_toggle_expand(self) -> None:
        """Toggle expand on all expandable widgets in subagent chat."""
        try:
            chat_view = self.query_one("#subagent-chat-view", ChatView)
            chat_view.toggle_expand("all")
            self._save_expand_state()
        except Exception:
            pass

    def action_quit_app(self) -> None:
        """Quit the application."""
        if self.app:
            self.app.exit()
