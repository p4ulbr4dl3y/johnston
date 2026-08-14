import asyncio
import logging
import time
from typing import Optional

from core.session_manager import is_ui_visible_user_message
from widgets.chat_view import ChatView

logger = logging.getLogger(__name__)


class SessionPersistenceMixin:
    """Session UI loading and persistence for JohnstonApp."""

    def load_session_ui(self, session_id: str) -> None:
        """Load session state into UI and agent history"""
        session = self.sm.get(session_id)
        if not session:
            return

        self.current_session_id = session_id
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
                            text = msg.get("text", "")
                            await chat_view.add_user_message(text, animate=False)
                        elif mtype == "bot":
                            text = msg.get("text", "")
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
                            await chat_view.add_tool_call(ttype, target, result_text=rtext, args=targs, animate=False)
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

            ctx = session.last_context_tokens
            if not ctx and self.agent.history:
                from core.infrastructure.runtime.token_util import estimate_tokens
                from core.prompt_builder import PromptBuilder

                is_subagent = getattr(self.agent, "is_subagent", False)
                builder = PromptBuilder(
                    self.agent.system_prompt,
                    self.agent.tools,
                    role=getattr(self.agent, "role", "worker"),
                    is_subagent=is_subagent,
                )
                sys_prompt = builder.build_system_prompt()
                all_tools = builder.build_tools(
                    provider_key=getattr(self.agent, "provider_key", "")
                )
                ctx = estimate_tokens(sys_prompt) + estimate_tokens(all_tools) + estimate_tokens(self.agent.history)
            self.agent.last_context_tokens = ctx

        self.refresh_status_footer()

    def _get_current_session_data(self) -> Optional[dict]:
        """Collect session data from the transcript session store (source of truth).

        The transcript (self.sm session .messages) is maintained on the SDK side
        via record_subagent_step during generation, so persistence no longer reads
        widget state. Title is derived from the first user message in the transcript.
        """
        session = self.sm.get(self.current_session_id, reload=False)
        if not session:
            return None

        messages = list(session.messages)

        title = ""
        for msg in messages:
            if isinstance(msg, dict) and msg.get("type") == "user" and is_ui_visible_user_message(msg):
                first_msg = msg.get("text", "")
                title = first_msg[:30] + "..." if len(first_msg) > 30 else first_msg
                break
        if not title:
            return None

        agent_history = getattr(self.agent, "history", [])

        return {
            "id": self.current_session_id,
            "title": title,
            "messages": messages,
            "agent_history": agent_history,
            "tokens_input": getattr(self.agent, "tokens_input", 0),
            "tokens_output": getattr(self.agent, "tokens_output", 0),
            "total_tokens": getattr(self.agent, "total_tokens", 0),
            "cost_usd": getattr(self.agent, "cost_usd", 0.0),
            "last_context_tokens": getattr(self.agent, "last_context_tokens", 0),
        }

    def save_current_session(self) -> None:
        """Save complete UI element state to ~/.johnston/projects/<project>/sessions"""
        session_data = self._get_current_session_data()
        if session_data is not None:
            self._write_session_data(session_data)
            self.refresh_status_footer()

    def _write_session_data(self, session_data: dict) -> None:
        """Write collected session data into the store (no UI access — safe for threads)."""
        session = self.sm.get(self.current_session_id, reload=False) or self.sm.create_main(self.current_session_id)
        session.description = session.description or session_data.get("title", "")
        session.messages = session_data.get("messages", [])
        session.agent_history = session_data.get("agent_history", [])
        session.tokens_input = session_data.get("tokens_input", 0)
        session.tokens_output = session_data.get("tokens_output", 0)
        session.total_tokens = session_data.get("total_tokens", 0)
        session.cost_usd = session_data.get("cost_usd", 0.0)
        session.last_context_tokens = session_data.get("last_context_tokens", 0)
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
