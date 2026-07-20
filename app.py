#!/usr/bin/env python3
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual import events, work

from mock_agent import MockAgent
from widgets.chat_view import ChatView
from widgets.chat_input import ChatInput

class TUIChatApp(App):
    """Минималистичный TUI чат с вечным фокусом на вводе"""

    CSS_PATH = "app.tcss"
    BINDINGS = [
        ("ctrl+c", "quit", "Выход"),
        ("ctrl+q", "quit", "Выход"),
        ("escape", "quit", "Выход"),
    ]

    def __init__(self):
        super().__init__()
        self.agent = MockAgent(persona_key="assistant")

    def compose(self) -> ComposeResult:
        with Vertical(id="app-container"):
            yield ChatView(id="chat-view")
            yield ChatInput(id="message-input", show_line_numbers=False)

    def on_mount(self) -> None:
        """Мгновенный фокус при старте"""
        self.query_one("#message-input", ChatInput).focus()

    def on_click(self, event: events.Click) -> None:
        """Любой клик мыши возвращает фокус в инпут"""
        self.query_one("#message-input", ChatInput).focus()

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Отправка текста и возврат фокуса"""
        user_text = event.value.strip()
        if not user_text:
            return
            
        chat_input = self.query_one("#message-input", ChatInput)
        chat_input.focus()
        self.generate_ai_response(user_text)

    @work(exclusive=True, thread=False)
    async def generate_ai_response(self, user_text: str) -> None:
        """Стриминг ответа ИИ"""
        chat_view = self.query_one(ChatView)
        
        await chat_view.add_user_message(user_text)
        bot_msg = await chat_view.add_bot_message()
        
        accumulated_text = ""
        async for chunk in self.agent.stream_response(user_text):
            accumulated_text += chunk
            bot_msg.content = accumulated_text
            chat_view.scroll_end(animate=False)

if __name__ == "__main__":
    TUIChatApp().run()
