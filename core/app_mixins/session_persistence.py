import asyncio
import time
from typing import Optional

from widgets.chat_view import (
    BotMessage,
    ChatView,
    CompactionDivider,
    ThinkingWidget,
    ToolCallWidget,
    UserMessage,
)


class SessionPersistenceMixin:
    """Session UI loading and persistence for JohnstonApp."""

    def load_session_ui(self, session_id: str) -> None:
        """Load session state into UI and agent history"""
        session_data = self.sm.load_session(session_id)
        if not session_data:
            return

        self.current_session_id = session_id
        self.sm.set_active_session_id(session_id)

        chat_view = self.query_one(ChatView)
        chat_view.loading = True
        chat_view._is_loading_session = True
        for child in list(chat_view.children):
            child.remove()

        # Restore complete element history in UI (user, bot, thinking, tool)
        saved_ui_msgs = session_data.get("ui_messages", [])

        async def _restore_ui_messages(msgs: list):
            try:
                for msg in msgs:
                    if not isinstance(msg, dict):
                        continue
                    try:
                        mtype = msg.get("type")
                        if mtype == "user":
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
                        elif mtype == "compaction_divider":
                            ctxt = msg.get("text", "Session Compacted")
                            await chat_view.add_compaction_divider(ctxt, animate=False)
                        if len(chat_view.children) % 5 == 0:
                            await asyncio.sleep(0)
                    except Exception as err:
                        print(f"Warning: error restoring UI message item: {err}")
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

        self.run_worker(_restore_ui_messages(saved_ui_msgs))

        # Restore agent context
        if hasattr(self.agent, "history"):
            self.agent.history = session_data.get("agent_history", [])
            self.agent.tokens_input = session_data.get("tokens_input", 0)
            self.agent.tokens_output = session_data.get("tokens_output", 0)
            self.agent.total_tokens = session_data.get("total_tokens", 0)
            self.agent.cost_usd = session_data.get("cost_usd", 0.0)

            ctx = session_data.get("last_context_tokens", 0)
            if not ctx and self.agent.history:
                from core.prompt_builder import PromptBuilder
                from core.token_util import estimate_tokens
                builder = PromptBuilder(self.agent.system_prompt, self.agent.tools, mode=getattr(self.agent, "mode", "act"))
                sys_prompt = builder.build_system_prompt()
                all_tools = builder.build_tools(provider_key=getattr(self.agent, "provider_key", ""), model_id=getattr(self.agent, "model", ""))
                ctx = estimate_tokens(sys_prompt) + estimate_tokens(all_tools) + estimate_tokens(self.agent.history)
            self.agent.last_context_tokens = ctx

        self.refresh_status_footer()

    def _get_current_session_data(self) -> Optional[dict]:
        """Safely collect UI state on the main thread."""
        try:
            chat_view = self.query_one(ChatView)
        except Exception:
            return None

        user_msgs = chat_view.get_user_messages()
        if not user_msgs:
            return {"ui_messages": []}

        first_msg = user_msgs[0][1]
        title = first_msg[:30] + "..." if len(first_msg) > 30 else first_msg

        ui_messages = []
        for child in chat_view.children:
            if isinstance(child, UserMessage):
                ui_messages.append({"type": "user", "text": child.raw_text})
            elif isinstance(child, BotMessage):
                ui_messages.append({"type": "bot", "text": child.content})
            elif isinstance(child, ThinkingWidget):
                ui_messages.append({
                    "type": "thinking",
                    "duration": getattr(child, "duration_seconds", 0.0),
                    "text": getattr(child, "thinking_text", "")
                })
            elif isinstance(child, ToolCallWidget):
                ui_messages.append({
                    "type": "tool",
                    "tool_type": getattr(child, "tool_type", ""),
                    "target": getattr(child, "target", ""),
                    "result_text": getattr(child, "result_text", ""),
                    "args": getattr(child, "args", {})
                })
            elif isinstance(child, CompactionDivider):
                ui_messages.append({
                    "type": "compaction_divider",
                    "text": getattr(child, "divider_title", "Session Compacted")
                })

        agent_history = getattr(self.agent, "history", [])

        return {
            "id": self.current_session_id,
            "title": title,
            "ui_messages": ui_messages,
            "agent_history": agent_history,
            "tokens_input": getattr(self.agent, "tokens_input", 0),
            "tokens_output": getattr(self.agent, "tokens_output", 0),
            "total_tokens": getattr(self.agent, "total_tokens", 0),
            "cost_usd": getattr(self.agent, "cost_usd", 0.0),
            "last_context_tokens": getattr(self.agent, "last_context_tokens", 0)
        }

    def save_current_session(self) -> None:
        """Save complete UI element state to ~/.johnston/projects/<project>/sessions"""
        session_data = self._get_current_session_data()
        if session_data is not None:
            self.sm.save_session(self.current_session_id, session_data)
            self.refresh_status_footer()

    async def save_current_session_async(self, force: bool = False) -> None:
        """Collect session data on main UI thread, then save to disk in background thread."""
        now = time.time()
        last_save = getattr(self, "_last_session_save_time", 0.0)
        if not force and (now - last_save < 1.5):
            return
        self._last_session_save_time = now
        session_data = self._get_current_session_data()
        if session_data is not None:
            await asyncio.to_thread(self.sm.save_session, self.current_session_id, session_data)
            self.refresh_status_footer()
