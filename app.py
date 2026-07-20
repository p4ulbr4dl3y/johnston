#!/usr/bin/env python3
from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Label
from textual import events, work

from mock_agent import MockAgent
from widgets.chat_view import ChatView
from widgets.chat_input import ChatInput
from widgets.command_suggestions import CommandSuggestions
from widgets.modal_screens import HelpScreen, ResumeScreen

class TUIChatApp(App):
    """TUI чат в стиле OpenCode CLI с синим акцентом слева и персиковым выделением подсказок"""

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
            yield CommandSuggestions(id="command-suggestions")
            with Vertical(id="input-container"):
                yield ChatInput(id="message-input", show_line_numbers=False)
                yield Label("[bold #3b82f6]Build[/bold #3b82f6] [dim]·[/dim] [bold #e0e0e0]Mock AI Agent[/bold #e0e0e0] [dim]Textual TUI[/dim]", id="input-status-bar")

    def on_mount(self) -> None:
        """Мгновенный фокус при старте"""
        self.query_one("#message-input", ChatInput).focus()

    def on_click(self, event: events.Click) -> None:
        """Любой клик мыши возвращает фокус в инпут"""
        self.query_one("#message-input", ChatInput).focus()

    def on_chat_input_submitted(self, event: ChatInput.Submitted) -> None:
        """Обработка ввода и слэш-команд (/help, /resume)"""
        user_text = event.value.strip()
        if not user_text:
            return
            
        chat_input = self.query_one("#message-input", ChatInput)
        chat_input.focus()

        # Слэш-команда /help
        if user_text.lower() == "/help":
            self.push_screen(HelpScreen())
            return

        # Слэш-команда /resume
        if user_text.lower() == "/resume":
            chat_view = self.query_one(ChatView)
            user_msgs = chat_view.get_user_messages()
            if not user_msgs:
                self.notify("История пуста: нет сообщений для отката", severity="warning")
                return

            def on_resume_selected(selected_idx: int | None) -> None:
                if selected_idx is not None and selected_idx >= 0:
                    chat_view.rollback_to(selected_idx)
                    self.notify("История успешно откачена!")
                self.query_one("#message-input", ChatInput).focus()

            self.push_screen(ResumeScreen(user_msgs), callback=on_resume_selected)
            return

        self.generate_ai_response(user_text)

    @work(exclusive=True, thread=False)
    async def generate_ai_response(self, user_text: str) -> None:
        """Пошаговая генерация ответа"""
        chat_view = self.query_one(ChatView)
        
        await chat_view.add_user_message(user_text)
        
        thinking_widget = None
        async for event_type, val1, val2 in self.agent.stream_steps(user_text):
            if event_type == "thinking_start":
                thinking_widget = await chat_view.add_thinking_widget(val1)
            elif event_type == "thinking_end":
                if thinking_widget:
                    duration = float(val1)
                    thinking_widget.finish_thinking(duration, val2)
            elif event_type == "tool":
                await chat_view.add_tool_call(val1, val2)
            elif event_type in ("bot_text", "outro"):
                bot_msg = await chat_view.add_bot_message()
                bot_msg.content = val1

if __name__ == "__main__":
    TUIChatApp().run()
