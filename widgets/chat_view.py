from textual.app import ComposeResult
from textual.containers import VerticalScroll, Vertical
from textual.widgets import Static, Markdown, Label
from textual.reactive import reactive

class UserMessage(Static):
    """Сообщение пользователя"""
    can_focus = False

    def __init__(self, content: str):
        self.raw_text = content
        super().__init__(f"[bold blue]Вы:[/] {content}", classes="user-msg")

class BotMessage(Vertical):
    """Сообщение ИИ"""
    can_focus = False
    content = reactive("")

    def __init__(self, persona_name: str = "ИИ"):
        super().__init__(classes="bot-msg")
        self.md_widget = Markdown("")

    def compose(self) -> ComposeResult:
        yield Label("✦ [bold green]ИИ:[/]", classes="bot-label")
        yield self.md_widget

    def watch_content(self, new_content: str) -> None:
        self.md_widget.update(new_content)


class ChatView(VerticalScroll):
    """Скроллируемый поток чата с поддержкой отката"""
    can_focus = False

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

    def get_user_messages(self) -> list[tuple[int, str]]:
        """Возвращает список (индекс_в_дереве, текст) всех сообщений пользователя"""
        result = []
        for idx, child in enumerate(self.children):
            if isinstance(child, UserMessage):
                result.append((idx, child.raw_text))
        return result

    def rollback_to(self, target_index: int) -> None:
        """Удаляет сообщения после выбранного элемента"""
        children = list(self.children)
        for child in children[target_index + 1:]:
            child.remove()
