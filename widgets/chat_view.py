from textual.app import ComposeResult
from textual.containers import VerticalScroll, Vertical
from textual.widgets import Static, Markdown, Label
from textual.reactive import reactive

class UserMessage(Static):
    """Сообщение пользователя без рамок"""
    def __init__(self, content: str):
        super().__init__(f"**Вы:** {content}", classes="user-msg")

class BotMessage(Vertical):
    """Сообщение ИИ без рамок"""
    content = reactive("")

    def __init__(self, persona_name: str = "ИИ"):
        super().__init__(classes="bot-msg")
        self.md_widget = Markdown("")

    def compose(self) -> ComposeResult:
        yield Label("✦ **ИИ:**", classes="bot-label")
        yield self.md_widget

    def watch_content(self, new_content: str) -> None:
        self.md_widget.update(new_content)


class ChatView(VerticalScroll):
    """Чистый поток чата без бабблов"""

    async def add_user_message(self, text: str) -> UserMessage:
        msg = UserMessage(text)
        await self.mount(msg)
        self.scroll_end(animate=True)
        return msg

    async def add_bot_message(self, persona_name: str = "ИИ") -> BotMessage:
        msg = BotMessage(persona_name=persona_name)
        await self.mount(msg)
        self.scroll_end(animate=True)
        return msg
