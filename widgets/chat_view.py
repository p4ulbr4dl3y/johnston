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


class ToolCallWidget(Static):
    """Красивый отдельный виджет вызова инструмента (Create, Read, Edit, Bash)"""
    can_focus = False

    def __init__(self, tool_type: str, target: str):
        self.tool_type = tool_type
        self.target = target
        
        icons = {
            "Create": "✨ Create",
            "Read": "📖 Read",
            "Edit": "📝 Edit",
            "Bash": "⚡ Bash"
        }
        header = icons.get(tool_type, f"● {tool_type}")
        
        # Формат: ● ToolType(target)
        super().__init__(
            f"[bold]{header}[/bold]({target})",
            classes=f"tool-call tool-{tool_type.lower()}"
        )


class ChatView(VerticalScroll):
    """Скроллируемый поток чата"""
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

    async def add_tool_call(self, tool_type: str, target: str) -> ToolCallWidget:
        """Добавление отдельного красивого виджета вызова инструмента"""
        widget = ToolCallWidget(tool_type, target)
        await self.mount(widget)
        self.scroll_end(animate=True)
        return widget

    def get_user_messages(self) -> list[tuple[int, str]]:
        result = []
        for idx, child in enumerate(self.children):
            if isinstance(child, UserMessage):
                result.append((idx, child.raw_text))
        return result

    def rollback_to(self, target_index: int) -> None:
        children = list(self.children)
        for child in children[target_index + 1:]:
            child.remove()
