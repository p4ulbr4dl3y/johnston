import os
import asyncio
from textual.widget import Widget

def _new_allow_select(self) -> bool:
    node = self
    while node is not None:
        if not getattr(node, "ALLOW_SELECT", True):
            return False
        node = node.parent
    return True

Widget.allow_select = property(_new_allow_select)

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual import events, work
from textual.widgets import Select

from provider_manager import ProviderManager
from session_manager import SessionManager
from widgets.chat_view import ChatView, UserMessage, BotMessage, ThinkingWidget, ToolCallWidget
from widgets.chat_input import ChatInput
from widgets.status_footer import StatusFooter
from widgets.command_suggestions import CommandSuggestions
from commands import handle_slash_command

class TUIChatApp(App):
    """Минималистичный TUI чат с конфигурацией провайдеров, моделей и изолированными сессиями по проектам"""

    CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.tcss")
    BINDINGS = [
        ("ctrl+c", "quit", "Exit"),
        ("ctrl+q", "quit", "Exit"),
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

    def refresh_status_footer(self) -> None:
        """Обновление строки директории, провайдера, модели, контекста, токенов и стоимости"""
        try:
            footer = self.query_one("#status-footer", StatusFooter)
            pkey = self.pm.get_active_provider_key()
            model_name = getattr(self.agent, "model", "")
            
            metrics = {}
            if hasattr(self.agent, "get_metrics"):
                metrics = self.agent.get_metrics()

            active_bg_tasks = len([t for t in getattr(self, "background_tasks", []) if getattr(t, "is_running", False)])

            footer.update_status(
                provider_key=pkey,
                model_name=model_name,
                directory=os.path.basename(os.path.realpath(os.getcwd())),
                active_bg_tasks=active_bg_tasks,
                total_tokens=metrics.get("total_tokens", 0),
                context_window=metrics.get("context", "128k"),
                context_limit=metrics.get("context_limit", 128000),
                cost_usd=metrics.get("cost_usd", 0.0)
            )
        except Exception:
            pass

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
                self.run_worker(chat_view.add_tool_call(ttype, target, result_text=rtext))

        # Восстановление контекста агента
        if hasattr(self.agent, "history"):
            self.agent.history = session_data.get("agent_history", [])
            self.agent.tokens_input = session_data.get("tokens_input", 0)
            self.agent.tokens_output = session_data.get("tokens_output", 0)
            self.agent.total_tokens = session_data.get("total_tokens", 0)

        self.refresh_status_footer()

    def save_current_session(self) -> None:
        """Сохранение полного состояния элементов UI в ~/.tui/projects/<project>/sessions"""
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
                    "result_text": getattr(child, "result_text", "")
                })

        agent_history = getattr(self.agent, "history", [])
        
        session_data = {
            "id": self.current_session_id,
            "title": title,
            "ui_messages": ui_messages,
            "agent_history": agent_history,
            "tokens_input": getattr(self.agent, "tokens_input", 0),
            "tokens_output": getattr(self.agent, "tokens_output", 0),
            "total_tokens": getattr(self.agent, "total_tokens", 0)
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
        """Переключение провайдера агента из конфига ~/.tui"""
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

    @work(exclusive=True, thread=False)
    async def generate_ai_response(self, user_text: str, show_in_ui: bool = True) -> None:
        """Потоковая генерация ответа с поддержкой отмены по Esc"""
        chat_view = self.query_one(ChatView)
        
        if show_in_ui:
            await chat_view.add_user_message(user_text)
            self.save_current_session()
        
        thinking_widget = None
        current_tool_widget = None
        bot_msg = None
        
        try:
            async for event_type, val1, val2 in self.agent.stream_steps(user_text):
                if event_type == "thinking_start":
                    thinking_widget = await chat_view.add_thinking_widget(val1)
                elif event_type == "thinking_end":
                    if thinking_widget:
                        duration = float(val1)
                        thinking_widget.finish_thinking(duration, val2)
                    thinking_widget = None
                elif event_type == "tool":
                    current_tool_widget = await chat_view.add_tool_call(val1, val2)
                    bot_msg = None
                elif event_type == "tool_result":
                    if current_tool_widget:
                        current_tool_widget.set_result(val1)
                elif event_type == "bot_chunk":
                    if bot_msg is None:
                        bot_msg = await chat_view.add_bot_message()
                    bot_msg.content += val1
                elif event_type in ("bot_text", "outro"):
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

import argparse

async def run_cli_prompt(prompt_text: str) -> None:
    from provider_manager import ProviderManager
    pm = ProviderManager()
    agent = pm.create_active_agent()
    print(f"Running prompt: {prompt_text}\n")
    
    async for event_type, val1, val2 in agent.stream_steps(prompt_text):
        if event_type == "thinking_start":
            print(f"Thinking...", end="", flush=True)
        elif event_type == "thinking_end":
            print(f" ({val1}s)")
        elif event_type == "tool":
            print(f"⚙ Tool: {val1}({val2})")
        elif event_type == "tool_result":
            res_preview = val1[:150] + "..." if len(val1) > 150 else val1
            print(f"↳ Result: {res_preview.strip()}")
        elif event_type in ("bot_text", "outro"):
            print(f"\nResponse:\n{val1}\n")

    metrics = agent.get_metrics()
    print(f"Tokens: {metrics.get('total_tokens', 0):,} tok | Context: {metrics.get('context', '128k')}")

def main():
    parser = argparse.ArgumentParser(description="TUI Chat AI Agent")
    parser.add_argument("-p", "--prompt", type=str, help="Run single prompt in non-interactive CLI mode")
    args, unknown = parser.parse_known_args()

    if args.prompt:
        asyncio.run(run_cli_prompt(args.prompt))
    else:
        TUIChatApp().run()

if __name__ == "__main__":
    main()
