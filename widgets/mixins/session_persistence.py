import asyncio
import logging
import threading
import time
from typing import Any, Optional

from widgets.presentation.widgets.chat_container import ChatView

logger = logging.getLogger(__name__)

_global_session_write_lock = threading.Lock()


class SessionPersistenceMixin:
    """Session UI loading and persistence for JohnstonApp."""

    def load_session_ui(self, session_id: str, read_only: bool = False) -> None:
        """Load session state into UI and agent history"""
        session = self.sm.get(session_id)
        if not session:
            return

        old_sid = getattr(self, "current_session_id", None)
        if old_sid and old_sid != session_id and hasattr(self.sm, "release_session_lock"):
            self.sm.release_session_lock(old_sid)

        self.current_session_id = session_id
        self.is_read_only = read_only

        try:
            from widgets.chat_input import ChatInput
            chat_input = self.query_one("#message-input", ChatInput)
            if read_only:
                chat_input.placeholder = "Type a message to fork & continue..."
            else:
                chat_input.placeholder = "Type a message or / for commands..."
        except Exception:
            pass

        if not read_only:
            if hasattr(self.sm, "acquire_session_lock"):
                self.sm.acquire_session_lock(session_id)
            self.sm.set_active_session_id(session_id)

        chat_view = self.query_one(ChatView)
        chat_view.loading = True
        chat_view._is_loading_session = True
        for child in list(chat_view.children):
            child.remove()

        try:
            from widgets.presentation.widgets.plan_notch import PlanNotch

            self.query_one(PlanNotch).clear_plan()
        except Exception:
            pass

        # Restore complete element history in UI (user, bot, thinking, tool) with pagination
        saved_msgs = session.messages

        from widgets.presentation.widgets.chat_container import restore_message_item

        async def _restore_messages(msgs: Any):
            try:
                msg_list = list(msgs) if msgs is not None else []
                raw_page_size = getattr(chat_view, "PAGE_SIZE", 50)
                page_size = raw_page_size if isinstance(raw_page_size, int) else 50
                if len(msg_list) > page_size:
                    chat_view._unloaded_messages = msg_list[:-page_size]
                    msgs_to_render = msg_list[-page_size:]
                else:
                    chat_view._unloaded_messages = []
                    msgs_to_render = msg_list

                task_mgr = getattr(self, "task_manager", None)
                for msg in msgs_to_render:
                    if not isinstance(msg, dict):
                        continue
                    try:
                        await restore_message_item(chat_view, msg, task_manager=task_mgr)
                        if len(getattr(chat_view, "children", [])) % 5 == 0:
                            await asyncio.sleep(0)
                    except Exception as err:
                        logger.warning("Error restoring UI message item: %s", err)
            except Exception as err:
                try:
                    self.notify(f"UI restoration failed: {err}", severity="warning")
                except Exception:
                    pass

            if hasattr(chat_view, "check_welcome") and callable(chat_view.check_welcome):
                chat_view.check_welcome()
            await asyncio.sleep(0.15)

            def _finish_session_load():
                try:
                    if hasattr(chat_view, "scroll_end"):
                        chat_view.scroll_end(animate=False)
                except Exception:
                    pass
                chat_view._is_loading_session = False
                chat_view.loading = False
                try:
                    from widgets.presentation.widgets.plan_notch import PlanNotch

                    notch = self.query_one(PlanNotch)
                    cur_plan = getattr(self, "current_plan", None)
                    if cur_plan:
                        notch.set_plan(cur_plan, getattr(self, "current_plan_explanation", ""))
                    else:
                        notch.clear_plan()
                except Exception:
                    pass

            try:
                if hasattr(chat_view, "call_after_refresh") and callable(chat_view.call_after_refresh):
                    chat_view.call_after_refresh(_finish_session_load)
                else:
                    _finish_session_load()
            except Exception:
                _finish_session_load()

        self.run_worker(_restore_messages(saved_msgs))

        # Restore agent context
        if self.agent is None and hasattr(self, "pm") and self.pm:
            try:
                self.agent = self.pm.create_active_agent(
                    role=session.role if hasattr(session, "role") and session.role else "worker"
                )
            except Exception:
                self.agent = None

        if self.agent is not None and hasattr(self.agent, "history"):
            self.agent.history = session.agent_history
            self.agent.tokens_input = session.tokens_input
            self.agent.tokens_output = session.tokens_output
            self.agent.total_tokens = session.total_tokens
            self.agent.cost_usd = session.cost_usd
            self.agent.tokens_cache_read = session.tokens_cache_read

            if hasattr(session, "role") and session.role:
                self.agent.role = session.role
                self.role = session.role
            else:
                self.agent.role = "worker"
                self.role = "worker"

            ctx = session.last_context_tokens
            if not ctx and self.agent.history:
                from widgets.app.session_state import recompute_context_tokens

                ctx = recompute_context_tokens(self.agent, session.last_context_tokens)
            self.agent.last_context_tokens = ctx
        elif hasattr(session, "role") and session.role:
            self.role = session.role

        # Restore active plan state from session messages
        restored_plan = None
        restored_explanation = ""
        try:
            msg_seq = list(saved_msgs) if saved_msgs is not None else []
            for msg in reversed(msg_seq):
                if isinstance(msg, dict) and msg.get("type") == "tool" and msg.get("tool_type") == "update_plan":
                    args = msg.get("args") or {}
                    if isinstance(args, dict) and isinstance(args.get("plan"), list):
                        restored_plan = [p for p in args.get("plan") if isinstance(p, dict)]
                        restored_explanation = str(args.get("explanation") or "").strip()
                        break
        except Exception:
            pass

        self.current_plan = restored_plan
        self.current_plan_explanation = restored_explanation
        self.refresh_status_footer()

    def _get_current_session_data(self) -> Optional[dict]:
        """Collect session data from the transcript session store (source of truth).

        Delegates collection to the pure aggregator in widgets/app/session_state.
        """
        from widgets.app.session_state import collect_session_data

        return collect_session_data(self)

    def save_current_session(self) -> None:
        """Save complete UI element state to ~/.johnston/projects/<project>/sessions"""
        session_data = self._get_current_session_data()
        if session_data is not None:
            self._write_session_data(session_data)
            self.refresh_status_footer()

    def _write_session_data(self, session_data: dict) -> None:
        """Write collected session data into the store (no UI access — safe for threads)."""
        if getattr(self, "is_read_only", False):
            return
        with _global_session_write_lock:
            existing = self.sm.get(self.current_session_id, reload=False)
            is_new = existing is None
            session = existing or self.sm.create_main(self.current_session_id)
            changed = is_new

            new_title = session_data.get("title")
            if new_title and session.title != new_title:
                session.title = new_title
                changed = True

            new_role = session_data.get("role")
            if new_role and session.role != new_role:
                session.role = new_role
                changed = True

            new_messages = session_data.get("messages", [])
            if session.messages != new_messages:
                session.messages = new_messages
                changed = True

            new_agent_history = session_data.get("agent_history", [])
            if session.agent_history != new_agent_history:
                session.agent_history = new_agent_history
                changed = True

            new_tok_in = session_data.get("tokens_input", 0)
            if session.tokens_input != new_tok_in:
                session.tokens_input = new_tok_in
                changed = True

            new_tok_out = session_data.get("tokens_output", 0)
            if session.tokens_output != new_tok_out:
                session.tokens_output = new_tok_out
                changed = True

            new_tot_tokens = session_data.get("total_tokens", 0)
            if session.total_tokens != new_tot_tokens:
                session.total_tokens = new_tot_tokens
                changed = True

            new_cost = session_data.get("cost_usd", 0.0)
            if session.cost_usd != new_cost:
                session.cost_usd = new_cost
                changed = True

            new_last_ctx = session_data.get("last_context_tokens", 0)
            if session.last_context_tokens != new_last_ctx:
                session.last_context_tokens = new_last_ctx
                changed = True

            new_cache_read = session_data.get("tokens_cache_read", 0)
            if session.tokens_cache_read != new_cache_read:
                session.tokens_cache_read = new_cache_read
                changed = True

            if changed:
                session.touch()
                self.sm.save(session)
            self.sm.set_active_session_id(self.current_session_id)

    async def save_current_session_async(self, force: bool = False) -> None:
        """Collect session data on main UI thread, then save to disk in background thread."""
        now = time.time()
        last_save = getattr(self, "_last_session_save_time", 0.0)
        if not force and (now - last_save < 1.5):
            return
        self._last_session_save_time = now
        session_data = self._get_current_session_data()
        if session_data is not None:
            await asyncio.to_thread(self._write_session_data, session_data)
            self.refresh_status_footer()

    def get_resume_hint(self) -> Optional[str]:
        """Return CLI command string to resume active session if it contains messages."""
        sid = getattr(self, "current_session_id", None)
        sm = getattr(self, "sm", None)
        if not sid or sm is None:
            return None
        try:
            sess = sm.get(sid)
            if sess and (getattr(sess, "messages", None) or getattr(sess, "agent_history", None)):
                return f"johnston --resume {sid}"
        except Exception:
            pass
        return None
