#!/usr/bin/env python3
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual import events, work
from textual.widgets import Select

from provider_manager import ProviderManager
from widgets.chat_view import ChatView
from widgets.chat_input import ChatInput
from widgets.command_suggestions import CommandSuggestions
from widgets.modal_screens import HelpScreen, RewindScreen

class TUIChatApp(App):
    """Минималистичный TUI чат с гибкой конфигурацией провайдеров из ~/.tui"""

    CSS_PATH = "app.tcss"
    BINDINGS = [
        ("ctrl+c", "quit", "Выход"),
        ("ctrl+q", "quit", "Выход"),
        ("escape", "quit", "Выход"),
    ]

    def __init__(self):
        super().__init__()
        self.pm = ProviderManager()
        self.agent = self.pm.create_active_agent()

    def compose(self) -> ComposeResult:
        with Vertical(id="app-container"):
            yield ChatView(id="chat-view")
            yield CommandSuggestions(id="command-suggestions")
            yield ChatInput(id="message-input", show_line_numbers=False)

    def on_mount(self) -> None:
        """Мгновенный фокус при старте"""
        self.query_one("#message-input", ChatInput).focus()

    def on_click(self, event: events.Click) -> None:
        """Любой клик мыши возвращает фокус в инпут"""
        self.query_one("#message-input", ChatInput).focus()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Переключение провайдера агента из конфига ~/.tui"""
        if event.value and isinstance(event.value, str) and event.value != "none":
            self.pm.set_active_provider_key(event.value)
            self.agent = self.pm.create_active_agent()
            self.notify(f"Агент переключен: {event.value}")

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Обработка ввода и слэш-команд (/help, /rewind)"""
        user_text = event.value.strip()
        if not user_text:
            return
            
        chat_input = self.query_one("#message-input", ChatInput)
        chat_input.focus()

        # Слэш-команда /help
        if user_text.lower() == "/help":
            self.push_screen(HelpScreen())
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
                    self.notify("История успешно откачена!")
                self.query_one("#message-input", ChatInput).focus()

            self.push_screen(RewindScreen(user_msgs), callback=on_rewind_selected)
            return

        self.generate_ai_response(user_text)

    @work(exclusive=True, thread=False)
    async def generate_ai_response(self, user_text: str) -> None:
        """Потоковая генерация ответа через текущего агента провайдера"""
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

if __name__ == "__main__":
    TUIChatApp().run()
