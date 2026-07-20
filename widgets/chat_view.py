from textual.app import ComposeResult
from textual.containers import VerticalScroll, Vertical
from textual.widgets import Static, Markdown, Label
from textual.reactive import reactive

class UserBubble(Static):
    """Минималистичное сообщение пользователя"""
    def __init__(self, content: str):
        super().__init__(content, classes="user-bubble")

class BotBubble(Vertical):
    """Минималистичное сообщение ИИ"""
    content = reactive("")

    def __init__(self, persona_name: str = "ИИ"):
        super().__init__(classes="bot-bubble")
        self.persona_name = persona_name
        self.md_widget = Markdown("")

    def compose(self) -> ComposeResult:
        yield Label("✦ ИИ", classes="bot-author")
        yield self.md_widget

    def watch_content(self, new_content: str) -> None:
        self.md_widget.update(new_content)


class ChatView(VerticalScroll):
    """Лента чата"""

    async def add_user_message(self, text: str) -> UserBubble:
        bubble = UserBubble(text)
        await self.mount(bubble)
        self.scroll_end(animate=True)
        return bubble

    async def add_bot_message(self, persona_name: str = "ИИ") -> BotBubble:
        bubble = BotBubble(persona_name=persona_name)
        await self.mount(bubble)
        self.scroll_end(animate=True)
        return bubble
