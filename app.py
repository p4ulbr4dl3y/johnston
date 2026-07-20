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
from widgets.command_suggestions import CommandSuggestions
from widgets.modal_screens import HelpScreen, RewindScreen, ResumeScreen, ProviderScreen, ModelScreen

class TUIChatApp(App):
    """Минималистичный TUI чат с конфигурацией провайдеров и изолированными сессиями по проектам"""

    CSS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "app.tcss")
    BINDINGS = [
        ("ctrl+c", "quit", "Выход"),
        ("ctrl+q", "quit", "Выход"),
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

    def on_mount(self) -> None:
        """Мгновенный фокус при старте (чистый новый диалог)"""
        self.query_one("#message-input", ChatInput).focus()

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
                self.run_worker(chat_view.add_tool_call(ttype, target))

        # Восстановление контекста агента
        if hasattr(self.agent, "history"):
            self.agent.history = session_data.get("agent_history", [])

    def save_current_session(self) -> None:
        """Сохранение полного состояния элементов UI в ~/.tui/projects/<project>/sessions"""
        chat_view = self.query_one(ChatView)
        user_msgs = chat_view.get_user_messages()
        
        if not user_msgs:
            # Если сообщений нет — удаляем запись с диска
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
                    "target": getattr(child, "target", "")
                })

        agent_history = getattr(self.agent, "history", [])
        
        session_data = {
            "id": self.current_session_id,
            "title": title,
            "ui_messages": ui_messages,
            "agent_history": agent_history
        }
        self.sm.save_session(self.current_session_id, session_data)

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
            self.notify(f"Агент переключен: {event.value}")

    async def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Обработка ввода и слэш-команд (/help, /new, /rewind, /resume)"""
        user_text = event.value.strip()
        if not user_text:
            return
            
        chat_input = self.query_one("#message-input", ChatInput)
        chat_input.focus()

        # Слэш-команда /help
        if user_text.lower() == "/help":
            self.push_screen(HelpScreen())
            return

        # Слэш-команда /new — сброс без создания немедленного файла на диске
        if user_text.lower() == "/new":
            self.current_session_id = self.sm.generate_session_id()
            chat_view = self.query_one(ChatView)
            await chat_view.remove_children()
            if hasattr(self.agent, "clear_history"):
                self.agent.clear_history()
            elif hasattr(self.agent, "history"):
                self.agent.history = []
            self.notify("Создан новый диалог!")
            return

        # Слэш-команда /provider
        if user_text.lower() == "/provider":
            providers = self.pm.load_providers()
            if not providers:
                self.notify("Нет доступных провайдеров", severity="warning")
                return

            def on_provider_selected(selected_key: str) -> None:
                if selected_key:
                    self.pm.set_active_provider_key(selected_key)
                    self.agent = self.pm.create_active_agent()
                    self.notify(f"Провайдер переключен: {selected_key}")
                self.query_one("#message-input", ChatInput).focus()

            self.push_screen(ProviderScreen(providers), callback=on_provider_selected)
            return

        # Слэш-команда /models
        if user_text.lower() == "/models":
            active_key = self.pm.get_active_provider_key()
            self.notify(f"Загрузка моделей для {active_key}...")
            models = await self.pm.fetch_models_for_provider(active_key)
            if not models:
                self.notify("Не удалось получить список моделей", severity="warning")
                return
            
            curr_model = getattr(self.agent, "model", "")
            
            def on_model_selected(selected_model: str) -> None:
                if selected_model:
                    if hasattr(self.agent, "model"):
                        self.agent.model = selected_model
                    self.notify(f"Модель переключена: {selected_model}")
                self.query_one("#message-input", ChatInput).focus()

            self.push_screen(ModelScreen(models, curr_model), callback=on_model_selected)
            return

        # Слэш-команда /rewind
        if user_text.lower() == "/rewind":
            chat_view = self.query_one(ChatView)
            user_msgs = chat_view.get_user_messages()
            if not user_msgs:
                self.notify("История пуста: нет сообщений для отката", severity="warning")
                return

            def on_rewind_selected(selected_idx: int | None) -> None:
                if selected_idx is not None and selected_idx >= 0:
                    chat_view.rollback_to(selected_idx)
                    if hasattr(self.agent, "clear_history"):
                        self.agent.clear_history()
                    elif hasattr(self.agent, "history"):
                        self.agent.history = []
                    self.save_current_session()
                    self.notify("История успешно откачена!")
                self.query_one("#message-input", ChatInput).focus()

            self.push_screen(RewindScreen(user_msgs), callback=on_rewind_selected)
            return

        # Слэш-команда /resume
        if user_text.lower() == "/resume":
            sessions = self.sm.list_sessions()
            if not sessions:
                self.notify("Нет сохраненных сессий в текущем проекте", severity="warning")
                return

            def on_resume_selected(selected_sid: str) -> None:
                if selected_sid:
                    self.load_session_ui(selected_sid)
                    self.notify(f"Сессия возобновлена: {selected_sid}")
                self.query_one("#message-input", ChatInput).focus()

            self.push_screen(ResumeScreen(sessions), callback=on_resume_selected)
            return

        self.generate_ai_response(user_text)

    @work(exclusive=True, thread=False)
    async def generate_ai_response(self, user_text: str) -> None:
        """Потоковая генерация ответа с автосохранением в сессию"""
        chat_view = self.query_one(ChatView)
        
        await chat_view.add_user_message(user_text)
        self.save_current_session()
        
        thinking_widget = None
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
                    await chat_view.add_tool_call(val1, val2)
                    bot_msg = None
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
                thinking_widget.finish_thinking(0.0, "Генерация остановлена (Esc).")
            if bot_msg:
                bot_msg.content += " *(прервано)*"
            self.notify("Ответ агента прерван (Esc)", severity="warning")
            raise
        finally:
            self.save_current_session()

def main():
    TUIChatApp().run()

if __name__ == "__main__":
    main()
