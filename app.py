import asyncio
import math
import os
import time

from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Select

from widgets.patch import apply_textual_patches

apply_textual_patches()


import logging

logger = logging.getLogger("johnston.app")

from cli import (
    get_version,
    main,
    print_mcp,
    print_models,
    print_modes,
    print_rules,
    print_skills,
    print_subagents,
    run_headless_prompt,
)

__all__ = [
    "JohnstonApp",
    "main",
    "get_version",
    "print_models",
    "print_skills",
    "print_mcp",
    "print_rules",
    "print_modes",
    "print_subagents",
    "run_headless_prompt",
]
from core.commands import handle_slash_command
from core.models_catalog import catalog
from core.provider_manager import ProviderManager
from core.session_manager import SessionManager
from widgets.chat_input import ChatInput
from widgets.chat_view import (
    BotMessage,
    ChatView,
    CompactionDivider,
    ThinkingWidget,
    ToolCallWidget,
    UserMessage,
    WelcomeWidget,
)
from widgets.command_suggestions import CommandSuggestions
from widgets.status_footer import StatusFooter


class JohnstonApp(App):
    """Minimalist Johnston TUI agent with provider/model configuration and isolated project sessions"""

    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.tcss")
    BINDINGS = [
        ("ctrl+c", "quit", "Exit"),
        ("ctrl+q", "quit", "Exit"),
        ("shift+tab", "toggle_mode", "Toggle Mode"),
        ("backtab", "toggle_mode", "Toggle Mode"),
    ]

    def __init__(
        self,
        mode: str | None = None,
        provider: str | None = None,
        model: str | None = None,
        resume_session_id: str | None = None,
    ):
        super().__init__()
        self._disable_tooltips = True
        self.pm = ProviderManager()
        if provider:
            self.pm.set_active_provider_key(provider)
        self.sm = SessionManager()
        self.agent = self.pm.create_active_agent()
        if model and self.agent:
            self.agent.model = model
        if mode and self.agent:
            self.agent.mode = mode
        self.mode = getattr(self.agent, "mode", mode or "action") if self.agent else (mode or "action")
        if self.agent:
            self.agent.app = self

        self.resume_session_id = resume_session_id
        if resume_session_id:
            sess = self.sm.load_session(resume_session_id)
            if sess:
                self.current_session_id = resume_session_id
            else:
                self.current_session_id = self.sm.generate_session_id()
        else:
            self.current_session_id = self.sm.generate_session_id()

        self.selection_copy_active = False
        self.background_tasks = []
        self.message_queue = []
        self.is_generating = False

    def action_toggle_mode(self) -> None:
        """Toggle agent mode across all registered modes (builtin, global, project)"""
        if not hasattr(self, "agent") or not self.agent:
            return
        from core.mode_manager import ModeManager

        available_modes = list(ModeManager.get_instance().load_modes().keys())
        curr = getattr(self.agent, "mode", "action").lower()
        next_idx = (available_modes.index(curr) + 1) % len(available_modes) if curr in available_modes else 0
        new_mode = available_modes[next_idx]
        self.agent.mode = new_mode
        self.mode = new_mode
        self.refresh_status_footer()

    def compose(self) -> ComposeResult:
        with Vertical(id="app-container"):
            yield ChatView(id="chat-view")
            yield CommandSuggestions(id="command-suggestions")
            yield ChatInput(id="message-input", show_line_numbers=False)
            yield StatusFooter(id="status-footer")

    def on_mount(self) -> None:
        """Instant focus on start, background catalog refresh and status bar refresh"""
        self.is_app_active = True
        self.query_one("#message-input", ChatInput).focus()
        if getattr(self, "resume_session_id", None):
            self.load_session_ui(self.resume_session_id)
        self.refresh_status_footer()
        asyncio.create_task(catalog.refresh())

    def on_unmount(self) -> None:
        """Clean up all running MCP servers and background processes when closing application"""
        self.is_app_active = False
        for task in getattr(self, "background_tasks", []):
            try:
                if hasattr(task, "kill_sync"):
                    task.kill_sync()
                elif hasattr(task, "kill") and asyncio.iscoroutinefunction(task.kill):
                    asyncio.create_task(task.kill())
                elif hasattr(task, "process") and task.process:
                    try:
                        task.process.terminate()
                    except Exception as err:
                        logger.debug(f"Process termination error: {err}")
                if hasattr(task, "read_task") and task.read_task:
                    task.read_task.cancel()
            except Exception as err:
                logger.debug(f"Task cleanup error: {err}")

        try:
            from core.mcp_manager import get_mcp_manager

            get_mcp_manager().stop_all()
        except Exception as err:
            logger.debug(f"MCP cleanup error: {err}")

    def refresh_status_footer(self) -> None:
        """Refresh status bar with directory, provider, model, context, tokens, and cost"""
        try:
            footer = self.query_one("#status-footer", StatusFooter)
            pkey = self.pm.get_active_provider_key()
            model_name = getattr(self.agent, "model", "")

            metrics = {}
            if hasattr(self.agent, "get_metrics"):
                metrics = self.agent.get_metrics()

            now = time.time()
            if not hasattr(self, "_status_cache_time") or (now - getattr(self, "_status_cache_time", 0)) > 3.0:
                from core.mcp_manager import get_mcp_manager
                from core.skill_manager import SkillManager

                self._cached_skills_count = len(SkillManager().list_skills())
                self._cached_mcp_servers = get_mcp_manager().load_servers()
                self._status_cache_time = now

            skills_count = getattr(self, "_cached_skills_count", 0)
            mcp_servers = getattr(self, "_cached_mcp_servers", [])
            mcp_total = len(mcp_servers)
            mcp_active = sum(1 for s in mcp_servers if not s.get("disabled", False))
            active_bg_tasks = len([t for t in getattr(self, "background_tasks", []) if getattr(t, "is_running", False)])

            agent_mode = getattr(self.agent, "mode", "action")

            thinking_effort = "auto"
            if hasattr(self.pm, "get_provider_thinking_effort"):
                thinking_effort = self.pm.get_provider_thinking_effort(pkey, model_name) or "auto"

            footer.update_status(
                provider_key=pkey,
                model_name=model_name,
                agent_mode=agent_mode,
                directory=os.path.basename(os.path.realpath(os.getcwd())),
                active_bg_tasks=active_bg_tasks,
                total_tokens=metrics.get("total_tokens", 0),
                context_used=metrics.get("context_used", 0),
                context_window=metrics.get("context", "128k"),
                context_limit=metrics.get("context_limit", 128000),
                cost_usd=metrics.get("cost_usd", 0.0),
                thinking_effort=thinking_effort,
                skills_count=skills_count,
                mcp_active=mcp_active,
                mcp_total=mcp_total
            )
        except Exception as e:
            print(f"Error refreshing status footer: {e}")

    def load_session_ui(self, session_id: str) -> None:
        """Load session state into UI and agent history"""
        session_data = self.sm.load_session(session_id)
        if not session_data:
            return

        self.current_session_id = session_id
        self.sm.set_active_session_id(session_id)

        chat_view = self.query_one(ChatView)
        for child in list(chat_view.children):
            child.remove()

        # Restore complete element history in UI (user, bot, thinking, tool)
        saved_ui_msgs = session_data.get("ui_messages", [])
        
        async def _restore_ui_messages(msgs: list):
            for msg in msgs:
                mtype = msg.get("type")
                if mtype == "user":
                    text = msg.get("text", "")
                    await chat_view.add_user_message(text)
                elif mtype == "bot":
                    text = msg.get("text", "")
                    bm = await chat_view.add_bot_message()
                    bm.content = text
                elif mtype == "thinking":
                    dur = msg.get("duration", 0.0)
                    txt = msg.get("text", "")
                    tw = await chat_view.add_thinking_widget()
                    tw.finish_thinking(dur, txt)
                elif mtype == "tool":
                    ttype = msg.get("tool_type", "")
                    target = msg.get("target", "")
                    rtext = msg.get("result_text", "")
                    targs = msg.get("args", {})
                    await chat_view.add_tool_call(ttype, target, result_text=rtext, args=targs)
                elif mtype == "compaction_divider":
                    ctxt = msg.get("text", "Session Compacted")
                    await chat_view.add_compaction_divider(ctxt)

            chat_view.check_welcome()
            try:
                chat_view.scroll_end(animate=False)
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
                builder = PromptBuilder(self.agent.system_prompt, self.agent.tools, mode=getattr(self.agent, "mode", "action"))
                sys_prompt = builder.build_system_prompt()
                all_tools = builder.build_tools(provider_key=getattr(self.agent, "provider_key", ""), model_id=getattr(self.agent, "model", ""))
                ctx = estimate_tokens(sys_prompt) + estimate_tokens(all_tools) + estimate_tokens(self.agent.history)
            self.agent.last_context_tokens = ctx

        self.refresh_status_footer()

    def save_current_session(self) -> None:
        """Save complete UI element state to ~/.johnston/projects/<project>/sessions"""
        chat_view = self.query_one(ChatView)
        user_msgs = chat_view.get_user_messages()

        if not user_msgs:
            self.sm.save_session(self.current_session_id, {"ui_messages": []})
            return

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

        session_data = {
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
        self.sm.save_session(self.current_session_id, session_data)
        self.refresh_status_footer()

    def on_click(self, event: events.Click) -> None:
        """Any mouse click returns focus to input unless text is selected or interacting with focusable widgets"""
        from textual.screen import ModalScreen
        if isinstance(self.screen, ModalScreen):
            return
        target = getattr(event, "widget", None) or getattr(event, "target", None)
        if isinstance(target, ChatView):
            self.screen.clear_selection()
        try:
            chat_view = self.query_one(ChatView)
            if chat_view.query(WelcomeWidget):
                self.screen.clear_selection()
        except Exception:
            pass
        if self.screen.get_selected_text() or getattr(self, "selection_copy_active", False):
            return
        if target and getattr(target, "can_focus", False) and target is not self.query_one("#message-input"):
            return
        if target and ("button" in getattr(target, "classes", []) or "copy" in str(getattr(target, "id", ""))):
            return
        try:
            self.query_one("#message-input", ChatInput).focus()
        except Exception:
            pass

    def on_mouse_down(self, event: events.MouseDown) -> None:
        """Track mouse down position to distinguish clicks from text drag selection"""
        self._mouse_down_pos = (event.screen_x, event.screen_y)

    def on_mouse_up(self, event: events.MouseUp) -> None:
        """On mouse up, copy selected fragment and clear selection"""
        down_pos = getattr(self, "_mouse_down_pos", None)
        self._mouse_down_pos = None

        if down_pos is not None:
            dx = abs(event.screen_x - down_pos[0])
            dy = abs(event.screen_y - down_pos[1])
            is_drag = (dx > 1 or dy > 1)
        else:
            is_drag = False

        try:
            chat_view = self.query_one(ChatView)
            if chat_view.query(WelcomeWidget):
                self.screen.clear_selection()
                return
        except Exception:
            pass

        target = getattr(event, "widget", None) or getattr(event, "target", None)
        if isinstance(target, ChatView):
            self.screen.clear_selection()
            return

        curr = target
        while curr:
            if isinstance(curr, WelcomeWidget):
                self.screen.clear_selection()
                return
            curr = getattr(curr, "parent", None)

        if not is_drag:
            self.screen.clear_selection()
            return

        selected_text = self.screen.get_selected_text()
        if selected_text and selected_text.strip():
            banner_signatures = ["|_|", "\\__\\___/", "___ _| |_", "_  ___ |", "johnston"]
            if any(sig in selected_text for sig in banner_signatures):
                self.screen.clear_selection()
                return
            try:
                self.selection_copy_active = True
                self.copy_to_clipboard(selected_text)
            except Exception as e:
                self.notify(f"Copy failed: {e}", severity="error")
            finally:
                self.screen.clear_selection()
                async def reset_flag():
                    await asyncio.sleep(0.05)
                    self.selection_copy_active = False
                asyncio.create_task(reset_flag())
        else:
            self.screen.clear_selection()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Switch agent provider from ~/.johnston config"""
        if event.value and isinstance(event.value, str) and event.value != "none":
            current_mode = getattr(self, "mode", getattr(self.agent, "mode", "action"))
            self.pm.set_active_provider_key(event.value)
            self.agent = self.pm.create_active_agent()
            self.agent.mode = current_mode
            self.agent.app = self
            self.mode = current_mode
            if hasattr(self.agent, "history"):
                sess = self.sm.load_session(self.current_session_id)
                if sess:
                    self.agent.history = sess.get("agent_history", [])
            self.refresh_status_footer()

    async def _exec_slash_command(self, user_text: str) -> None:
        try:
            processed = await handle_slash_command(self, user_text)
            if not processed:
                if user_text.startswith("/") and len(user_text.split()) == 1:
                    self.notify("Unknown command", severity="warning")
                else:
                    if self.is_generating:
                        self.message_queue.append((user_text, True))
                    else:
                        self.trigger_ai_response(user_text, show_in_ui=True)
        except Exception as e:
            self.notify(f"Error executing command: {e}", severity="error")

    async def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Handle input and slash commands (/help, /new, /skills)"""
        user_text = event.value.strip()
        if not user_text:
            return

        chat_input = self.query_one("#message-input", ChatInput)
        chat_input.focus()

        if "/" in user_text:
            asyncio.create_task(self._exec_slash_command(user_text))
            return

        if self.is_generating:
            self.message_queue.append((user_text, True))
        else:
            self.trigger_ai_response(user_text, show_in_ui=True)

    def trigger_ai_response(self, prompt: str, show_in_ui: bool = False) -> None:
        """Safely trigger AI response generation, or queue prompt if currently generating."""
        if getattr(self, "is_generating", False):
            self.message_queue.append((prompt, show_in_ui))
        else:
            self.is_generating = True
            self.generate_ai_response(prompt, show_in_ui=show_in_ui)

    @work(exclusive=True, thread=False)
    async def generate_ai_response(self, user_text: str, show_in_ui: bool = True) -> None:
        """Stream AI response generation with cancellation support via Esc"""
        if not getattr(self.agent, "model", ""):
            self.notify("No model selected. Please select a model from /models.", severity="warning")
            from core.commands import ModelsCommand
            await ModelsCommand().execute(self)
            self.is_generating = False
            return

        self.is_generating = True
        chat_view = self.query_one(ChatView)

        if show_in_ui:
            await chat_view.add_user_message(user_text)
            self.save_current_session()
            curr_sid = getattr(self, "current_session_id", None)
            if curr_sid:
                user_msgs = chat_view.get_user_messages()
                msg_idx = len(user_msgs) - 1
                try:
                    proj_path = getattr(self.sm, "project_path", None) if hasattr(self, "sm") else None
                    from core.git_checkpoint import GitCheckpointManager
                    await asyncio.to_thread(GitCheckpointManager.create_checkpoint, curr_sid, msg_idx, project_path=proj_path)
                except Exception as e:
                    print(f"Git checkpoint creation failed: {e}")

        full_prompt = user_text

        thinking_widget = None
        current_tool_widget = None
        bot_msg = None

        start_time = time.time()
        try:
            try:
                footer = self.query_one("#status-footer", StatusFooter)
                footer.set_generating(True)
            except Exception:
                pass

            async for step in self.agent.stream_steps(full_prompt):
                event_type = step[0]
                val1 = step[1] if len(step) > 1 else ""
                val2 = step[2] if len(step) > 2 else ""
                val3 = step[3] if len(step) > 3 else None

                if event_type == "thinking_start":
                    thinking_widget = await chat_view.add_thinking_widget(val1)
                elif event_type == "thinking_delta":
                    if thinking_widget:
                        thinking_widget.update_thinking(val1)
                elif event_type == "thinking_end":
                    if thinking_widget:
                        try:
                            duration = float(val1)
                            if not math.isfinite(duration):
                                duration = 0.0
                        except Exception:
                            duration = 0.0
                        thinking_widget.finish_thinking(duration, val2)
                    thinking_widget = None
                elif event_type == "tool":
                    if bot_msg and not bot_msg.content.strip():
                        bot_msg.remove()
                    bot_msg = None
                    targs = val3 if isinstance(val3, dict) else {}
                    current_tool_widget = await chat_view.add_tool_call(val1, val2, args=targs)
                    self.current_tool_widget = current_tool_widget
                elif event_type == "tool_result":
                    if current_tool_widget:
                        current_tool_widget.set_result(val1)
                elif event_type in ("bot_chunk", "bot_delta"):
                    if val1.strip():
                        if bot_msg is None:
                            bot_msg = await chat_view.add_bot_message()
                        if event_type == "bot_delta":
                            bot_msg.content = val1
                        else:
                            bot_msg.content += val1
                elif event_type in ("bot_text", "outro"):
                    if val1.strip():
                        if bot_msg is None:
                            bot_msg = await chat_view.add_bot_message()
                        bot_msg.content = val1
                        bot_msg = None
                elif event_type == "compaction_divider":
                    await chat_view.add_compaction_divider(val1 or "Session Compacted")
                    self.refresh_status_footer()
        except (asyncio.CancelledError, RuntimeError):
            self.message_queue.clear()
            if thinking_widget:
                try:
                    duration = time.time() - start_time
                    thinking_widget.finish_thinking(duration)
                except Exception:
                    pass
            if hasattr(self, "agent") and hasattr(self.agent, "history"):
                partial = (bot_msg.content if bot_msg else "").strip()
                if partial:
                    self.agent.history.append({"role": "assistant", "content": partial})
                self.agent.history.append({"role": "user", "content": "[System Note: Response interrupted by user]"})
            try:
                await chat_view.add_compaction_divider("Response Interrupted")
            except Exception:
                pass
            if getattr(self, "is_app_active", True):
                try:
                    self.notify("Agent response interrupted (Esc)", severity="warning")
                except Exception:
                    pass
        finally:
            try:
                footer = self.query_one("#status-footer", StatusFooter)
                footer.set_generating(False)
            except Exception:
                pass
            try:
                if getattr(self, "is_app_active", True):
                    self.save_current_session()
            except Exception:
                pass
            # Drain the queue atomically: if a queued message exists, dispatch it WITHOUT
            # clearing is_generating first. Clearing it early opens a window where a
            # concurrent user input bypasses the queue and cancels this queued item via
            # the exclusive worker. Only return to idle when the queue is empty.
            queued_next = None
            if self.message_queue and getattr(self, "is_app_active", True):
                queued_next = self.message_queue.pop(0)
            if queued_next is not None:
                self.generate_ai_response(queued_next[0], show_in_ui=queued_next[1])
            else:
                self.is_generating = False

    def on_background_shell_completed(self, task_id: str, command_str: str, result: str) -> None:
        """Callback when background shell command finishes"""
        if not getattr(self, "is_app_active", True):
            return
        try:
            self.notify(f"Background command completed (TID: {task_id})")
            msg = f"[System Notification] Background command '{command_str}' (TID: {task_id}) completed.\nOutput:\n{result}"
            if self.is_generating:
                self.message_queue.append((msg, False))
            else:
                self.generate_ai_response(msg, show_in_ui=False)
        except Exception:
            pass

if __name__ == "__main__":
    main()
