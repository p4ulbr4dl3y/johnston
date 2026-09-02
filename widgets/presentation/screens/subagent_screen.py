import asyncio

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen

from core.domain.policies.messages import is_ui_visible_user_message
from widgets.presentation.widgets.chat_container import ChatView
from widgets.presentation.widgets.chat_stream_driver import ChatStreamDriver
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
        self.driver: ChatStreamDriver | None = None
        self._last_tool_widget = None
        self.event_queue = asyncio.Queue()
        self.queue_task = None

    @property
    def thinking_widget(self):
        d = getattr(self, "driver", None)
        return d.thinking_handle if d else getattr(self, "_legacy_thinking_widget", None)

    @thinking_widget.setter
    def thinking_widget(self, val):
        d = getattr(self, "driver", None)
        if d:
            d.thinking_handle = val
        self._legacy_thinking_widget = val

    @property
    def bot_msg(self):
        d = getattr(self, "driver", None)
        return d.bot_handle if d else getattr(self, "_legacy_bot_msg", None)

    @bot_msg.setter
    def bot_msg(self, val):
        d = getattr(self, "driver", None)
        if d:
            d.bot_handle = val
        self._legacy_bot_msg = val

    @property
    def current_tool_widget(self):
        d = getattr(self, "driver", None)
        if d and d.tool_handles:
            return d.tool_handles[-1]
        return getattr(self, "_last_tool_widget", None)

    @current_tool_widget.setter
    def current_tool_widget(self, val):
        self._last_tool_widget = val
        d = getattr(self, "driver", None)
        if d and val:
            if not d.tool_handles or d.tool_handles[-1] != val:
                d.tool_handles.append(val)

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

    def _on_plan_update(self, plan: list, explanation: str) -> None:
        try:
            self.query_one(PlanNotch).set_plan(plan, explanation)
        except Exception:
            pass

    async def _load_history_session(self) -> None:
        chat_view = self.query_one("#subagent-chat-view", ChatView)
        chat_view.loading = True
        chat_view._is_loading_session = True
        try:
            self.query_one(PlanNotch).clear_plan()
        except Exception:
            pass

        for child in list(chat_view.children):
            child.remove()

        self.driver = ChatStreamDriver(
            chat_view,
            on_tool_widget=lambda w: setattr(self, "_last_tool_widget", w),
            on_plan_update=self._on_plan_update,
        )

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
            if not has_user_msg and getattr(self.session, "prompt", None):
                await chat_view.add_user_message(self.session.prompt, animate=False)

            for idx, evt in enumerate(history_events):
                is_last_running = is_running and (idx == len(history_events) - 1)
                await self.driver.consume_session_event(
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

        if not is_running and self.driver:
            await self.driver.finalize_bot_stream()

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
        if getattr(self, "driver", None) is None:
            try:
                chat_view = self.query_one("#subagent-chat-view", ChatView)
            except Exception:
                chat_view = getattr(self, "chat_view", None)
            self.driver = ChatStreamDriver(
                chat_view,
                on_tool_widget=lambda w: setattr(self, "_last_tool_widget", w),
                on_plan_update=self._on_plan_update,
            )
            if getattr(self, "_legacy_bot_msg", None):
                self.driver.bot_handle = self._legacy_bot_msg
            if getattr(self, "_legacy_thinking_widget", None):
                self.driver.thinking_handle = self._legacy_thinking_widget
            if getattr(self, "_last_tool_widget", None):
                self.driver.tool_handles.append(self._last_tool_widget)

        await self.driver.consume_session_event(
            evt,
            animate=animate,
            is_expanded=is_expanded,
            is_active=is_active,
        )

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
