#!/usr/bin/env python3
from textual.app import App, ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widgets import Header, Footer, Input, Button, Label, Select, OptionList
from textual import work

from mock_agent import MockAgent, PERSONAS
from widgets.sidebar import Sidebar
from widgets.chat_view import ChatView

class TUIChatApp(App):
    """Главное TUI приложение чата с ИИ агентом"""

    CSS_PATH = "app.tcss"
    BINDINGS = [
        ("ctrl+b", "toggle_sidebar", "Сайдбар"),
        ("ctrl+n", "new_chat", "Новый чат"),
        ("ctrl+l", "clear_chat", "Очистить"),
        ("ctrl+q", "quit", "Выход"),
    ]

    def __init__(self):
        super().__init__()
        self.agent = MockAgent(persona_key="assistant")
        self.chat_count = 1

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        
        yield Sidebar(id="sidebar")

        with Vertical(id="main-container"):
            yield Label("💬 Диалог #1 — 🤖 AI Assistant", id="chat-header")
            yield ChatView(id="chat-view")
            
            with Horizontal(id="input-container"):
                yield Input(placeholder="Введите сообщение (Enter для отправки)...", id="message-input")
                yield Button("Отправить", id="btn-send", variant="primary")

        yield Footer()

    async def on_mount(self) -> None:
        """Приветственное сообщение при запуске"""
        chat_view = self.query_one(ChatView)
        welcome_bubble = await chat_view.add_bot_message(persona_name=PERSONAS["assistant"]["name"])
        welcome_bubble.content = (
            "Привет! Я **TUI ИИ-Агент**.\n\n"
            "Задайте мне любой вопрос или выберите другую персону в боковой панели.\n"
            "Поддерживается **потоковый вывод** и форматирование `Markdown`."
        )

    def action_toggle_sidebar(self) -> None:
        """Скрыть / показать сайдбар"""
        sidebar = self.query_one(Sidebar)
        sidebar.display = not sidebar.display

    def action_new_chat(self) -> None:
        """Создать новый чат"""
        self.chat_count += 1
        session_list = self.query_one("#session-list", OptionList)
        new_title = f"Чат #{self.chat_count}"
        session_list.add_option(new_title)
        
        self.action_clear_chat()
        
        # Обновить заголовок
        persona_info = PERSONAS[self.agent.persona_key]
        header_label = self.query_one("#chat-header", Label)
        header_label.update(f"💬 Диалог #{self.chat_count} — {persona_info['name']}")

    def action_clear_chat(self) -> None:
        """Очистить текущий чат"""
        chat_view = self.query_one(ChatView)
        chat_view.remove_children()

    def on_select_changed(self, event: Select.Changed) -> None:
        """Изменение персоны агента в сайдбаре"""
        if event.select.id == "persona-select" and event.value != Select.BLANK:
            persona_key = str(event.value)
            self.agent.set_persona(persona_key)
            persona_info = PERSONAS[persona_key]
            
            # Обновляем заголовок
            header_label = self.query_one("#chat-header", Label)
            header_label.update(f"💬 Диалог #{self.chat_count} — {persona_info['name']}")
            
            # Уведомление
            self.notify(f"Агент изменен на: {persona_info['name']}")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Обработка нажатия Enter в поле ввода"""
        self.send_user_message()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Обработка клика по кнопкам"""
        if event.button.id == "btn-send":
            self.send_user_message()
        elif event.button.id == "btn-new-chat":
            self.action_new_chat()

    def send_user_message(self) -> None:
        """Отправка сообщения пользователя и запуск асинхронного ответа ИИ"""
        input_widget = self.query_one("#message-input", Input)
        user_text = input_widget.value.strip()
        
        if not user_text:
            return
            
        # Сброс поля ввода
        input_widget.value = ""

        # Запускаем генерацию (которая сама добавит сообщения)
        self.generate_ai_response(user_text)

    @work(exclusive=True, thread=False)
    async def generate_ai_response(self, user_text: str) -> None:
        """Асинхронный воркер для добавления сообщений и стриминга ответа"""
        chat_view = self.query_one(ChatView)
        persona_info = PERSONAS[self.agent.persona_key]
        
        # Добавляем юзер баббл
        await chat_view.add_user_message(user_text)

        # Добавляем бот баббл
        bot_bubble = await chat_view.add_bot_message(persona_name=persona_info["name"])
        
        accumulated_text = ""
        async for chunk in self.agent.stream_response(user_text):
            accumulated_text += chunk
            bot_bubble.content = accumulated_text
            chat_view.scroll_end(animate=False)

if __name__ == "__main__":
    app = TUIChatApp()
    app.run()
