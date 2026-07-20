#!/usr/bin/env python3
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual import events, work
from textual.widgets import Select

from provider_manager import ProviderManager
from session_manager import SessionManager
from widgets.chat_view import ChatView
from widgets.chat_input import ChatInput
from widgets.command_suggestions import CommandSuggestions
from widgets.modal_screens import HelpScreen, RewindScreen, ResumeScreen

class TUIChatApp(App):
    """Минималистичный TUI чат с гибкой конфигурацией провайдеров и системой сессий из ~/.tui"""

    CSS_PATH = "app.tcss"
    BINDINGS = [
        ("ctrl+c", "quit", "Выход"),
        ("ctrl+q", "quit", "Выход"),
        ("escape", "quit", "Выход"),
    ]

    def __init__(self):
        super().__init__()
        self.pm = ProviderManager()
        self.sm = SessionManager()
        self.agent = self.pm.create_active_agent()
        self.current_session_id = self.sm.get_active_session_id()

    def compose(self) -> ComposeResult:
        with Vertical(id="app-container"):
            yield ChatView(id="chat-view")
            yield CommandSuggestions(id="command-suggestions")
            yield ChatInput(id="message-input", show_line_numbers=False)

    def on_mount(self) -> None:
        """Загрузка активной сессии и мгновенный фокус при старте"""
        self.query_one("#message-input", ChatInput).focus()
        self.load_session_ui(self.current_session_id)

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

        # Восстановление истории сообщений в UI
        saved_ui_msgs = session_data.get("ui_messages", [])
        for msg in saved_ui_msgs:
            mtype = msg.get("type")
            text = msg.get("text", "")
            if mtype == "user":
                self.run_worker(chat_view.add_user_message(text))
            elif mtype == "bot":
                async def add_bot(txt=text):
                    bm = await chat_view.add_bot_message()
                    bm.content = txt
                self.run_worker(add_bot())

        # Восстановление контекста агента
        if hasattr(self.agent, "history"):
            self.agent.history = session_data.get("agent_history", [])

    def save_current_session(self, user_text: str = None, bot_text: str = None) -> None:
        """Сохранение состояния сессии на диск в ~/.tui/sessions"""
        chat_view = self.query_one(ChatView)
        user_msgs = chat_view.get_user_messages()
        
        title = "Новый диалог"
        if user_msgs:
            first_msg = user_msgs[0][1]
            title = first_msg[:30] + "..." if len(first_msg) > 30 else first_msg

        ui_messages = []
        for child in chat_view.children:
            if hasattr(child, "raw_text"):
                ui_messages.append({"type": "user", "text": child.raw_text})
            elif hasattr(child, "content") and getattr(child, "content", None):
                ui_messages.append({"type": "bot", "text": child.content})

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

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Обработка ввода и слэш-команд (/help, /rewind, /resume)"""
        user_text = event.value.strip()
        if not user_text:
            return
            
        chat_input = self.query_one("#message-input", ChatInput)
        chat_input.focus()

        # Слэш-команда /help
        if user_text.lower() == "/help":
            self.push_screen(HelpScreen())
            return

        # Слэш-команда /new
        if user_text.lower() == "/new":
            new_sid = self.sm.create_session("Новый диалог")
            self.load_session_ui(new_sid)
            self.notify("Создана новая сессия!")
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
                    self.save_current_session()
                    self.notify("История успешно откачена!")
                self.query_one("#message-input", ChatInput).focus()

            self.push_screen(RewindScreen(user_msgs), callback=on_rewind_selected)
            return

        # Слэш-команда /resume
        if user_text.lower() == "/resume":
            sessions = self.sm.list_sessions()
            if not sessions:
                self.notify("Нет сохраненных сессий для возобновления", severity="warning")
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
        
        thinking_widget = None
        bot_msg = None
        
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

        self.save_current_session()

if __name__ == "__main__":
    TUIChatApp().run()
