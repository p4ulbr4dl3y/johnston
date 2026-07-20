import os
import asyncio
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
        self.current_session_id = self.sm.generate_session_id()

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

            footer.update_status(
                provider_key=pkey,
                model_name=model_name,
                directory=os.path.basename(os.path.realpath(os.getcwd())),
                total_tokens=metrics.get("total_tokens", 0),
                context_window=metrics.get("context", "128k"),
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
            "agent_history": agent_history
        }
        self.sm.save_session(self.current_session_id, session_data)
        self.refresh_status_footer()

    def on_click(self, event: events.Click) -> None:
        """Любой клик мыши возвращает фокус в инпут"""
        self.query_one("#message-input", ChatInput).focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Переключение провайдера агента из конфига ~/.tui"""
        if event.value and isinstance(event.value, str) and event.value != "none":
            self.pm.set_active_provider_key(event.value)
            self.agent = self.pm.create_active_agent()
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
    async def generate_ai_response(self, user_text: str) -> None:
        """Потоковая генерация ответа с поддержкой отмены по Esc"""
        chat_view = self.query_one(ChatView)
        
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

def main():
    TUIChatApp().run()

if __name__ == "__main__":
    main()
