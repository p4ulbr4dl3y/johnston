import asyncio
import math
import os
import sys
import time
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

try:
    import tomllib
except ImportError:
    tomllib = None  # type: ignore

from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Select

from widgets.patch import apply_textual_patches

apply_textual_patches()


from core.commands import handle_slash_command
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


def get_version() -> str:
    """Get application version dynamically from metadata or pyproject.toml"""
    try:
        return version("johnston")
    except PackageNotFoundError:
        pyproject = Path(__file__).parent / "pyproject.toml"
        if pyproject.exists() and tomllib:
            try:
                with open(pyproject, "rb") as f:
                    data = tomllib.load(f)
                    return data.get("project", {}).get("version", "0.1.0-dev")
            except Exception:
                pass
        return "0.1.0-dev"


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
        """Instant focus on start and refresh status bar"""
        self.is_app_active = True
        self.query_one("#message-input", ChatInput).focus()
        if getattr(self, "resume_session_id", None):
            self.load_session_ui(self.resume_session_id)
        self.refresh_status_footer()

    def on_unmount(self) -> None:
        """Clean up all running MCP servers and background processes when closing application"""
        self.is_app_active = False
        for task in getattr(self, "background_tasks", []):
            try:
                if hasattr(task, "kill") and asyncio.iscoroutinefunction(task.kill):
                    asyncio.create_task(task.kill())
                elif hasattr(task, "process") and task.process:
                    try:
                        task.process.terminate()
                    except Exception:
                        pass
                if hasattr(task, "read_task") and task.read_task:
                    task.read_task.cancel()
            except Exception:
                pass

        try:
            from core.mcp_manager import get_mcp_manager
            get_mcp_manager().stop_all()
        except Exception:
            pass

    def refresh_status_footer(self) -> None:
        """Refresh status bar with directory, provider, model, context, tokens, and cost"""
        try:
            footer = self.query_one("#status-footer", StatusFooter)
            pkey = self.pm.get_active_provider_key()
            model_name = getattr(self.agent, "model", "")

            metrics = {}
            if hasattr(self.agent, "get_metrics"):
                metrics = self.agent.get_metrics()

            from core.mcp_manager import get_mcp_manager
            from core.skill_manager import SkillManager

            skills_count = len(SkillManager().list_skills())
            mcp_servers = get_mcp_manager().load_servers()
            mcp_total = len(mcp_servers)
            mcp_active = sum(1 for s in mcp_servers if not s.get("disabled", False))
            active_bg_tasks = len([t for t in getattr(self, "background_tasks", []) if getattr(t, "is_running", False)])

            agent_mode = getattr(self.agent, "mode", "action")

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
        for msg in saved_ui_msgs:
            mtype = msg.get("type")
            if mtype == "user":
                text = msg.get("text", "")
                self.run_worker(chat_view.add_user_message(text))
            elif mtype == "bot":
                text = msg.get("text", "")
                async def add_bot(txt=text):
                    bm = await chat_view.add_bot_message()
                    bm.content = txt
                self.run_worker(add_bot())
            elif mtype == "thinking":
                dur = msg.get("duration", 0.0)
                txt = msg.get("text", "")
                async def add_thinking(duration=dur, content=txt):
                    tw = await chat_view.add_thinking_widget()
                    tw.finish_thinking(duration, content)
                self.run_worker(add_thinking())
            elif mtype == "tool":
                ttype = msg.get("tool_type", "")
                target = msg.get("target", "")
                rtext = msg.get("result_text", "")
                targs = msg.get("args", {})
                self.run_worker(chat_view.add_tool_call(ttype, target, result_text=rtext, args=targs))
            elif mtype == "compaction_divider":
                ctxt = msg.get("text", "Session Compacted")
                self.run_worker(chat_view.add_compaction_divider(ctxt))

        chat_view.check_welcome()

        def _scroll_to_bottom():
            try:
                chat_view.scroll_end(animate=False)
            except Exception:
                pass

        self.call_after_refresh(_scroll_to_bottom)
        try:
            loop = asyncio.get_running_loop()
            loop.call_later(0.1, _scroll_to_bottom)
            loop.call_later(0.3, _scroll_to_bottom)
        except Exception:
            pass

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

    async def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Handle input and slash commands (/help, /new)"""
        user_text = event.value.strip()
        if not user_text:
            return

        chat_input = self.query_one("#message-input", ChatInput)
        chat_input.focus()

        if user_text.startswith("/"):
            processed = await handle_slash_command(self, user_text)
            if not processed:
                self.notify("Unknown command", severity="warning")
            return

        if self.is_generating:
            self.message_queue.append((user_text, True))
        else:
            self.trigger_ai_response(user_text, show_in_ui=True)

    def prepare_prompt_with_attachments(self, user_text: str):
        """Search for @path/to/file and raw paths in user_text and attach text files and images"""
        import base64
        import mimetypes
        import re

        pattern = r'@(?:"([^"]+)"|\'([^\']+)\'|([^\s]+))|(?:^|\s)(/(?:\\ |\S)+|~/(?:\\ |\S)+|file://(?:\\ |\S)+)'
        matches = re.findall(pattern, user_text)
        if not matches:
            return user_text

        text_attachments = []
        image_parts = []
        cwd = os.getcwd()
        seen = set()

        for m1, m2, m3, m4 in matches:
            raw_path = m1 or m2 or m3 or m4
            clean_path = raw_path.replace("\\ ", " ").rstrip(".,!?:;)]}")
            if not clean_path or clean_path in seen:
                continue

            expanded_path = os.path.expanduser(clean_path)
            full_path = expanded_path if os.path.isabs(expanded_path) else os.path.join(cwd, expanded_path)

            if os.path.isfile(full_path):
                seen.add(clean_path)
                try:
                    ext = os.path.splitext(full_path)[1].lower()
                    if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tiff", ".svg"):
                        mime_type, _ = mimetypes.guess_type(full_path)
                        if not mime_type or not mime_type.startswith("image/"):
                            mime_type = f"image/{ext.lstrip('.')}" if ext in (".png", ".jpeg", ".gif", ".webp") else "image/png"
                        with open(full_path, "rb") as img_f:
                            b64_data = base64.b64encode(img_f.read()).decode("utf-8")
                        b64_url = f"data:{mime_type};base64,{b64_data}"
                        image_parts.append({
                            "type": "image_url",
                            "image_url": {"url": b64_url}
                        })
                        text_attachments.append(f"--- Attached Image File: {clean_path} ---")
                    else:
                        with open(full_path, "r", encoding="utf-8", errors="replace") as f:
                            content = f.read()
                        if len(content) > 50000:
                            content = content[:50000] + "\n... [content truncated]"
                        text_attachments.append(f"--- Attached File: {clean_path} ---\n{content}")
                except Exception as e:
                    print(f"Error reading attached file {clean_path}: {e}")

        final_text = user_text
        if text_attachments:
            final_text = user_text + "\n\n" + "\n\n".join(text_attachments)

        if image_parts:
            return [{"type": "text", "text": final_text}] + image_parts
        return final_text

    def trigger_ai_response(self, prompt: str, show_in_ui: bool = False) -> None:
        """Safely trigger AI response generation, or queue prompt if currently generating."""
        if getattr(self, "is_generating", False):
            self.message_queue.append((prompt, show_in_ui))
        else:
            # Set the flag synchronously before dispatching the @work coroutine. The
            # worker only sets is_generating=True once it starts running, leaving a
            # window where a second trigger could bypass the queue and cancel the
            # first exclusive worker.
            self.is_generating = True
            self.generate_ai_response(prompt, show_in_ui=show_in_ui)

    @work(exclusive=True, thread=False)
    async def generate_ai_response(self, user_text: str, show_in_ui: bool = True) -> None:
        """Stream AI response generation with cancellation support via Esc"""
        if not getattr(self.agent, "model", ""):
            self.notify("No model selected. Please select a model from /models.", severity="warning")
            from core.commands import ModelsCommand
            await ModelsCommand().execute(self)
            # trigger_ai_response may have set is_generating=True synchronously before
            # dispatching this worker; clear it so the app returns to idle on early exit.
            self.is_generating = False
            return

        self.is_generating = True
        chat_view = self.query_one(ChatView)

        if show_in_ui:
            await chat_view.add_user_message(user_text)
            self.save_current_session()

        full_prompt = self.prepare_prompt_with_attachments(user_text)

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

    def on_background_bash_completed(self, task_id: str, command_str: str, result: str) -> None:
        """Callback when background bash command finishes"""
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

def print_models():
    """Print available providers and models to stdout"""
    pm = ProviderManager()
    providers = pm.load_providers()
    active_key = pm.get_active_provider_key()
    print("Available Johnston Providers & Models:\n")
    for key, info in providers.items():
        api_key = pm.get_api_key(key) or info.get("api_key", "")
        models = info.get("models") or ([info["model"]] if info.get("model") else [])
        if not api_key and not models and key != "opencode":
            continue
        is_active = "*" if key == active_key else " "
        name = info.get("name") or info.get("NAME") or key
        model = info.get("model") or info.get("MODEL") or (models[0] if models else "not configured")
        desc = info.get("description") or info.get("DESCRIPTION") or ""
        print(f"{is_active} [{key}] {name}")
        if model and model != "not configured":
            print(f"    Active Model: {model}")
        if desc:
            print(f"    Description: {desc}")
        print()


def print_skills():
    """Print available skills to stdout"""
    from core.skill_manager import SkillManager
    skills = SkillManager().list_skills()
    print("Available Johnston Skills:\n")
    if not skills:
        print("  No skills found (~/.johnston/skills/ or .johnston/skills/)")
        return
    for s in skills:
        scope = f"[{s.get('scope', 'global')}]"
        print(f"  * {s.get('name', 'unnamed')} {scope}")
        if s.get("description"):
            print(f"    Description: {s.get('description')}")
        if s.get("path"):
            print(f"    Path: {s.get('path')}")
        print()


def print_mcp():
    """Print configured MCP servers to stdout"""
    from core.mcp_manager import get_mcp_manager
    servers = get_mcp_manager().load_servers()
    print("Configured MCP Servers:\n")
    if not servers:
        print("  No MCP servers configured (~/.johnston/mcp.json or .johnston/mcp.json)")
        return
    for s in servers:
        status = "[disabled]" if s.get("disabled", False) else "[active]"
        print(f"  * {s.get('name')} {status}")
        cmd = s.get("command")
        if isinstance(cmd, list):
            cmd = " ".join(cmd)
        print(f"    Command: {cmd}")
        print()


def print_rules():
    """Print active project instructions and rules to stdout"""
    from core.prompt_builder import get_project_instructions_snippet, get_rules_snippet
    print("Active Rules & Project Instructions:\n")
    instructions = get_project_instructions_snippet()
    rules = get_rules_snippet()
    if not instructions and not rules:
        print("  No rules or project instruction files found (AGENTS.md, CLAUDE.md, .cursorrules, .rules/).")
        return
    if instructions:
        print("=== Project Instructions ===")
        print(instructions)
        print()
    if rules:
        print("=== Global & Local Rules ===")
        print(rules)
        print()


def print_modes():
    """Print available agent execution modes to stdout"""
    from core.mode_manager import ModeManager
    modes = ModeManager.get_instance().load_modes()
    print("Available Agent Execution Modes:\n")
    for key, m in modes.items():
        ro_str = " (read-only)" if m.read_only else ""
        print(f"  • {m.name} ({m.key}){ro_str} [{m.source}]")
        if m.description:
            print(f"    Description: {m.description}")
        if m.disallowed_tools:
            print(f"    Disallowed tools: {', '.join(m.disallowed_tools)}")
        print()



def print_subagents():
    from core.subagent_registry import SubagentRegistry
    from core.subagent_tracker import SubagentTracker
    registry = SubagentRegistry.get_instance()
    defs = registry.list_definitions()
    print("Available Subagent Definitions:")
    for dname, dval in defs.items():
        print(f"  • {dname} [{dval.source}] — {dval.description}")

    tracker = SubagentTracker.get_instance()
    sessions = list(tracker.sessions.values())
    if sessions:
        print("\nRegistered Subagent Sessions:")
        for sess in sessions:
            print(f"  • ID: {sess.task_id} | Status: {sess.status.upper()} | Type: {sess.subagent_type} | Description: {sess.description}")


def run_headless_prompt(
    prompt: str,
    mode: str | None = None,
    provider: str | None = None,
    model: str | None = None,
    quiet: bool = False,
    verbose: bool = False,
):
    """Execute a single prompt headless via CLI with clean stdout piping and stderr tool logging"""
    pm = ProviderManager()
    if provider:
        pm.set_active_provider_key(provider)
    agent = pm.create_active_agent()
    if not agent:
        sys.stderr.write("Error: Could not initialize AI agent provider.\n")
        sys.exit(1)
    if model and agent:
        agent.model = model
    if mode and agent:
        agent.mode = mode

    async def _runner():
        last_printed_len = 0
        async for step in agent.stream_steps(prompt):
            chunk_type = step[0]
            val1 = step[1] if len(step) > 1 else ""
            val2 = step[2] if len(step) > 2 else ""

            if chunk_type in ("bot_delta", "bot_text", "text"):
                if len(val1) < last_printed_len:
                    last_printed_len = 0
                new_text = val1[last_printed_len:]
                if new_text:
                    sys.stdout.write(new_text)
                    sys.stdout.flush()
                    last_printed_len = len(val1)
            elif not quiet:
                if chunk_type in ("thinking_start", "thinking_delta") and verbose:
                    sys.stderr.write(f"\r[Thinking: {val1[:80]}...]\x1b[K")
                    sys.stderr.flush()
                elif chunk_type == "thinking_end" and verbose:
                    sys.stderr.write(f"\n[Thought for {val1}s]\n")
                    sys.stderr.flush()
                elif chunk_type == "tool":
                    last_printed_len = 0
                    sys.stderr.write(f"\n[Executing Tool: {val1} ({val2})]\n")
                    sys.stderr.flush()
                elif chunk_type == "tool_result" and verbose:
                    sys.stderr.write(f"[Tool Result: {str(val1)[:150]}...]\n")
                    sys.stderr.flush()
        sys.stdout.write("\n")
        sys.stdout.flush()

    asyncio.run(_runner())


def main():
    import argparse

    parser = argparse.ArgumentParser(
        prog="johnston",
        description="Johnston Coding Agent",
    )
    parser.add_argument("-p", "--prompt", help="Run a single prompt in CLI headless mode")
    parser.add_argument(
        "-m",
        "--mode",
        choices=["action", "explore"],
        help="Agent execution mode ('action' or 'explore')",
    )
    parser.add_argument("--provider", help="Set active provider key (e.g. opencode)")
    parser.add_argument("--model", help="Set active model ID")
    parser.add_argument("--resume", help="Resume specific session ID")
    parser.add_argument("-q", "--quiet", action="store_true", help="Suppress tool execution logs on stderr")
    parser.add_argument("--verbose", action="store_true", help="Show detailed thinking and tool output logs on stderr")
    parser.add_argument("--models", action="store_true", help="List available providers and models")
    parser.add_argument("--skills", action="store_true", help="List available skills")
    parser.add_argument("--mcp", action="store_true", help="List configured MCP servers")
    parser.add_argument("--modes", action="store_true", help="List available agent execution modes")
    parser.add_argument("--rules", action="store_true", help="List active project instructions and rules")
    parser.add_argument("--subagents", action="store_true", help="List available subagent definitions and sessions")
    parser.add_argument("--init", action="store_true", help="Initialize or update AGENTS.md guide for repo")
    parser.add_argument("-v", "--version", action="store_true", help="Show application version")

    args = parser.parse_args()

    if args.version:
        print(f"johnston {get_version()}")
        sys.exit(0)

    if args.modes:
        print_modes()
        sys.exit(0)

    if args.models:
        print_models()
        sys.exit(0)

    if args.skills:
        print_skills()
        sys.exit(0)

    if args.mcp:
        print_mcp()
        sys.exit(0)

    if args.rules:
        print_rules()
        sys.exit(0)

    if args.subagents:
        print_subagents()
        sys.exit(0)

    # Check for stdin piped input (e.g. cat file | johnston -p "...")
    stdin_input = ""
    if not sys.stdin.isatty():
        try:
            stdin_input = sys.stdin.read().strip()
        except Exception:
            pass

    target_prompt = args.prompt or ""
    if stdin_input:
        target_prompt = f"Piped Stdin Content:\n{stdin_input}\n\nTask: {target_prompt}".strip()

    if args.init:
        from core.commands import INIT_PROMPT_TEMPLATE
        run_headless_prompt(
            prompt=INIT_PROMPT_TEMPLATE,
            mode=args.mode,
            provider=args.provider,
            model=args.model,
            quiet=args.quiet,
            verbose=args.verbose,
        )
        sys.exit(0)

    if target_prompt:
        run_headless_prompt(
            prompt=target_prompt,
            mode=args.mode,
            provider=args.provider,
            model=args.model,
            quiet=args.quiet,
            verbose=args.verbose,
        )
        sys.exit(0)

    app = JohnstonApp(
        mode=args.mode,
        provider=args.provider,
        model=args.model,
        resume_session_id=args.resume,
    )
    app.run()

    if getattr(app, "current_session_id", None) and hasattr(app, "sm"):
        try:
            sess = app.sm.load_session(app.current_session_id)
            if sess and (sess.get("ui_messages") or sess.get("agent_history")):
                print(f"\nTo resume this session, run:\n  johnston --resume {app.current_session_id}")
        except Exception:
            pass


if __name__ == "__main__":
    main()

