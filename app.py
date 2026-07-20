#!/usr/bin/env python3
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Input
from textual import work

from mock_agent import MockAgent
from widgets.chat_view import ChatView

class TUIChatApp(App):
    """Супер-чистый TUI чат"""

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
            yield Input(placeholder="Написать...", id="message-input")

    async def on_mount(self) -> None:
        """Приветствие"""
        chat_view = self.query_one(ChatView)
        welcome_msg = await chat_view.add_bot_message()
        welcome_msg.content = (
            "Привет. Введи текст и нажми `Enter`.\n"
            "`Ctrl+C` или `Esc` — выход."
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Отправка по Enter"""
        user_text = event.value.strip()
        if not user_text:
            return
            
        event.input.value = ""
        self.generate_ai_response(user_text)

    @work(exclusive=True, thread=False)
    async def generate_ai_response(self, user_text: str) -> None:
        """Стриминг ответа"""
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
