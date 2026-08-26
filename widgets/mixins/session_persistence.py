import asyncio
import logging
import threading
import time
from typing import Optional

from core.domain.policies.messages import is_ui_visible_user_message
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

        # Restore complete element history in UI (user, bot, thinking, tool)
        saved_msgs = session.messages

        async def _restore_messages(msgs: list):
            try:
                for msg in msgs:
                    if not isinstance(msg, dict):
                        continue
                    try:
                        mtype = msg.get("type")
                        if mtype == "user":
                            if not is_ui_visible_user_message(msg):
                                continue
                            text = msg.get("display_text") or msg.get("text", "")
                            att_count = msg.get("attachments_count", 0)
                            if not att_count and msg.get("attachments"):
                                att_count = len(msg.get("attachments"))
                            await chat_view.add_user_message(
                                text,
                                animate=False,
                                attachments_count=att_count,
                            )
                        elif mtype == "bot":
                            text = msg.get("text", "")
                            if not text.strip():
                                continue
                            bm = await chat_view.add_bot_message(animate=False)
                            await bm.set_final_content(text)
                        elif mtype == "thinking":
                            dur = msg.get("duration", 0.0)
                            txt = msg.get("text", "")
                            tw = await chat_view.add_thinking_widget(animate=False)
                            tw.finish_thinking(dur, txt)
                        elif mtype == "tool":
                            ttype = msg.get("tool_type", "")
                            target = msg.get("target", "")
                            rtext = msg.get("result_text", "")
                            targs = msg.get("args", {})
                            status = msg.get("status")
                            if not ttype and not target and not targs and status == "cancelled":
                                continue
                            if status == "running":
                                task_id = None
                                if "[Background Task ID:" in (rtext or ""):
                                    import re

                                    bg_m = re.search(r"Background Task ID:\s*([^\s\]]+)", rtext)
                                    if bg_m:
                                        task_id = bg_m.group(1)
                                mgr = getattr(self, "task_manager", None)
                                is_live = bool(task_id and mgr is not None and getattr(mgr, "_tasks", {}).get(task_id) is not None)
                                if not is_live:
                                    status = "done" if rtext else "cancelled"
                            elif not status and not rtext:
                                status = "cancelled"
                            await chat_view.add_tool_call(
                                ttype,
                                target,
                                result_text=rtext,
                                args=targs,
                                status=status,
                                returncode=msg.get("returncode"),
                                animate=False,
                            )
                        elif mtype == "event_divider":
                            ctxt = msg.get("text", "Session Compacted")
                            await chat_view.add_event_divider(ctxt, animate=False)
                        elif mtype == "status_change":
                            pass
                        if len(chat_view.children) % 5 == 0:
                            await asyncio.sleep(0)
                    except Exception as err:
                        logger.warning("Error restoring UI message item: %s", err)
            except Exception as err:
                try:
                    self.notify(f"UI restoration failed: {err}", severity="warning")
                except Exception:
                    pass

            chat_view.check_welcome()
            await asyncio.sleep(0.15)
            chat_view._is_loading_session = False
            chat_view.loading = False
            try:
                chat_view.call_after_refresh(chat_view.scroll_end, animate=False)
            except Exception:
                pass

        self.run_worker(_restore_messages(saved_msgs))

        # Restore agent context
        if hasattr(self.agent, "history"):
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
            session = self.sm.get(self.current_session_id, reload=False) or self.sm.create_main(self.current_session_id)
            session.description = session.description or session_data.get("title", "")
            if "role" in session_data:
                session.role = session_data["role"]
            session.messages = session_data.get("messages", [])
            session.agent_history = session_data.get("agent_history", [])
            session.tokens_input = session_data.get("tokens_input", 0)
            session.tokens_output = session_data.get("tokens_output", 0)
            session.total_tokens = session_data.get("total_tokens", 0)
            session.cost_usd = session_data.get("cost_usd", 0.0)
            session.last_context_tokens = session_data.get("last_context_tokens", 0)
            session.tokens_cache_read = session_data.get("tokens_cache_read", 0)
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
