import asyncio
import os

from textual import events, work
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Select

from widgets.patch import apply_textual_patches

apply_textual_patches()


from commands import handle_slash_command
from core.provider_manager import ProviderManager
from core.session_manager import SessionManager
from widgets.chat_input import ChatInput
from widgets.chat_view import BotMessage, ChatView, ThinkingWidget, ToolCallWidget, UserMessage
from widgets.command_suggestions import CommandSuggestions
from widgets.status_footer import StatusFooter


class JohnstonChatApp(App):
    """Минималистичный Johnston чат с конфигурацией провайдеров, моделей и изолированными сессиями по проектам"""

    ENABLE_COMMAND_PALETTE = False
    CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.tcss")
    BINDINGS = [
        ("ctrl+c", "quit", "Exit"),
        ("ctrl+q", "quit", "Exit"),
        ("shift+tab", "toggle_mode", "Toggle Mode"),
        ("backtab", "toggle_mode", "Toggle Mode"),
    ]

    def __init__(self):
        super().__init__()
        self.pm = ProviderManager()
        self.sm = SessionManager()
        self.agent = self.pm.create_active_agent()
        self.agent.app = self
        self.current_session_id = self.sm.generate_session_id()
        self.selection_copy_active = False
        self.background_tasks = []

    def action_toggle_mode(self) -> None:
        """Цикличное переключение режима агента (Build / Plan / Ask / Debug / Orchestrator)"""
        if not hasattr(self, "agent") or not self.agent:
            return
        modes = ["build", "plan", "ask", "debug", "orchestrator"]
        curr = getattr(self.agent, "mode", "build").lower()
        next_idx = (modes.index(curr) + 1) % len(modes) if curr in modes else 0
        new_mode = modes[next_idx]
        self.agent.mode = new_mode
        self.refresh_status_footer()

    def compose(self) -> ComposeResult:
        with Vertical(id="app-container"):
            yield ChatView(id="chat-view")
            yield CommandSuggestions(id="command-suggestions")
            yield ChatInput(id="message-input", show_line_numbers=False)
            yield StatusFooter(id="status-footer")

    def on_mount(self) -> None:
        """Мгновенный фокус при старте и обновление строки состояния"""
        self.query_one("#message-input", ChatInput).focus()
        self.refresh_status_footer()

    def on_unmount(self) -> None:
        """Очистка всех запущенных MCP-серверов при закрытии приложения"""
        try:
            from core.mcp_manager import get_mcp_manager
            get_mcp_manager().stop_all()
        except Exception:
            pass

    def refresh_status_footer(self) -> None:
        """Обновление строки директории, провайдера, модели, контекста, токенов и стоимости"""
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

            agent_mode = getattr(self.agent, "mode", "build")

            footer.update_status(
                provider_key=pkey,
                model_name=model_name,
                agent_mode=agent_mode,
                directory=os.path.basename(os.path.realpath(os.getcwd())),
                active_bg_tasks=active_bg_tasks,
                total_tokens=metrics.get("total_tokens", 0),
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
        """Загрузка состояния сессии в UI и в историю агента"""
        session_data = self.sm.load_session(session_id)
        if not session_data:
            return

        self.current_session_id = session_id
        self.sm.set_active_session_id(session_id)

        chat_view = self.query_one(ChatView)
        for child in list(chat_view.children):
            child.remove()

        # Восстановление полной истории элементов в UI (user, bot, thinking, tool)
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

        chat_view.check_welcome()

        # Восстановление контекста агента
        if hasattr(self.agent, "history"):
            self.agent.history = session_data.get("agent_history", [])
            self.agent.tokens_input = session_data.get("tokens_input", 0)
            self.agent.tokens_output = session_data.get("tokens_output", 0)
            self.agent.total_tokens = session_data.get("total_tokens", 0)
            self.agent.cost_usd = session_data.get("cost_usd", 0.0)

        self.refresh_status_footer()

    def save_current_session(self) -> None:
        """Сохранение полного состояния элементов UI в ~/.johnston/projects/<project>/sessions"""
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

        agent_history = getattr(self.agent, "history", [])

        session_data = {
            "id": self.current_session_id,
            "title": title,
            "ui_messages": ui_messages,
            "agent_history": agent_history,
            "tokens_input": getattr(self.agent, "tokens_input", 0),
            "tokens_output": getattr(self.agent, "tokens_output", 0),
            "total_tokens": getattr(self.agent, "total_tokens", 0),
            "cost_usd": getattr(self.agent, "cost_usd", 0.0)
        }
        self.sm.save_session(self.current_session_id, session_data)
        self.refresh_status_footer()

    def on_click(self, event: events.Click) -> None:
        """Любой клик мыши возвращает фокус в инпут"""
        self.query_one("#message-input", ChatInput).focus()

    def on_mouse_up(self, event: events.MouseUp) -> None:
        """При отпускании мыши копирует выделенный фрагмент и сбрасывает выделение"""
        selected_text = self.screen.get_selected_text()
        if selected_text:
            try:
                self.selection_copy_active = True
                self.copy_to_clipboard(selected_text)
                self.notify("Selected text copied to clipboard!")
            except Exception as e:
                self.notify(f"Copy failed: {e}", severity="error")
            finally:
                self.screen.clear_selection()
                async def reset_flag():
                    await asyncio.sleep(0.05)
                    self.selection_copy_active = False
                asyncio.create_task(reset_flag())

    def on_select_changed(self, event: Select.Changed) -> None:
        """Переключение провайдера агента из конфига ~/.johnston"""
        if event.value and isinstance(event.value, str) and event.value != "none":
            self.pm.set_active_provider_key(event.value)
            self.agent = self.pm.create_active_agent()
            self.agent.app = self
            if hasattr(self.agent, "history"):
                sess = self.sm.load_session(self.current_session_id)
                if sess:
                    self.agent.history = sess.get("agent_history", [])
            self.refresh_status_footer()
            self.notify(f"Agent switched: {event.value}")

    async def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Обработка ввода и слэш-команд (/help, /new, /provider, /models, /rewind, /resume)"""
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

        self.generate_ai_response(user_text)

    def prepare_prompt_with_attachments(self, user_text: str):
        """Поиск @path/to/file и прямых путей в user_text и прикрепление текстовых файлов и картинок"""
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

    @work(exclusive=True, thread=False)
    async def generate_ai_response(self, user_text: str, show_in_ui: bool = True) -> None:
        """Потоковая генерация ответа с поддержкой отмены по Esc"""
        chat_view = self.query_one(ChatView)

        if show_in_ui:
            await chat_view.add_user_message(user_text)
            self.save_current_session()

        full_prompt = self.prepare_prompt_with_attachments(user_text)

        thinking_widget = None
        current_tool_widget = None
        bot_msg = None

        try:
            async for step in self.agent.stream_steps(full_prompt):
                event_type = step[0]
                val1 = step[1] if len(step) > 1 else ""
                val2 = step[2] if len(step) > 2 else ""
                val3 = step[3] if len(step) > 3 else None

                if event_type == "thinking_start":
                    thinking_widget = await chat_view.add_thinking_widget(val1)
                elif event_type == "thinking_end":
                    if thinking_widget:
                        duration = float(val1)
                        thinking_widget.finish_thinking(duration, val2)
                    thinking_widget = None
                elif event_type == "tool":
                    if bot_msg and not bot_msg.content.strip():
                        bot_msg.remove()
                    bot_msg = None
                    targs = val3 if isinstance(val3, dict) else {}
                    current_tool_widget = await chat_view.add_tool_call(val1, val2, args=targs)
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
        except asyncio.CancelledError:
            if thinking_widget:
                thinking_widget.finish_thinking(0.0, "Generation stopped (Esc).")
            if bot_msg:
                bot_msg.content += " *(interrupted)*"
            self.notify("Agent response interrupted (Esc)", severity="warning")
            raise
        finally:
            self.save_current_session()

    def on_background_bash_completed(self, task_id: str, command_str: str, result: str) -> None:
        """Вызывается при завершении фоновой bash команды"""
        self.notify(f"Background command completed (TID: {task_id})")
        msg = f"[System Notification] Background command '{command_str}' (TID: {task_id}) completed.\nOutput:\n{result}"
        self.generate_ai_response(msg, show_in_ui=False)

def main():
    JohnstonChatApp().run()

if __name__ == "__main__":
    main()
