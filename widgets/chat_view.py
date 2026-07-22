from textual.app import ComposeResult
from textual.containers import Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Label, Markdown, Static


class UserMessage(Static):
    """Сообщение пользователя"""
    can_focus = False

    def __init__(self, content: str):
        self.raw_text = content
        super().__init__(content, classes="user-msg")


class BotMessage(Vertical):
    """Сообщение ИИ с полным рендерингом Markdown"""
    can_focus = False
    content = reactive("")

    def __init__(self):
        super().__init__(classes="bot-msg")
        self.md_widget = Markdown("")

    def compose(self) -> ComposeResult:
        yield self.md_widget

    def watch_content(self, new_content: str) -> None:
        self.md_widget.update(new_content)


class ThinkingWidget(Vertical):
    """Виджет думания с поддержкой Markdown при разворачивании"""
    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, thinking_text: str = "Thinking..."):
        super().__init__(classes="thinking-widget thinking-active")
        self.thinking_text = thinking_text
        self.duration_seconds = 0.0
        self.is_thinking = True
        self.spinner_frames = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        self.spinner_idx = 0

        self.header_label = Label("⠋ Thinking...", classes="thinking-header")
        self.md_widget = Markdown("")

    def compose(self) -> ComposeResult:
        yield self.header_label
        yield self.md_widget

    def on_mount(self) -> None:
        self.md_widget.display = False
        self.set_interval(0.08, self.animate_spinner)

    def animate_spinner(self) -> None:
        if self.is_thinking:
            self.spinner_idx = (self.spinner_idx + 1) % len(self.spinner_frames)
            frame = self.spinner_frames[self.spinner_idx]
            self.header_label.update(f"{frame} Thinking...")

    def finish_thinking(self, duration: float, thinking_content: str = "") -> None:
        self.is_thinking = False
        self.duration_seconds = duration
        if thinking_content:
            self.thinking_text = thinking_content
        self.remove_class("thinking-active")
        self.md_widget.update(self.thinking_text)
        self.render_collapsed()

    def render_collapsed(self) -> None:
        self.is_expanded = False
        self.header_label.update(f"Thought for {self.duration_seconds:.1f} sec")
        self.md_widget.display = False


class ToolCallWidget(Vertical):
    """Виджет вызова инструмента (Create, Read, Edit, Bash)"""
    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, tool_type: str, target: str, result_text: str = "", is_sequential: bool = False):
        classes = f"tool-call tool-{tool_type.lower()}"
        if is_sequential:
            classes += " tool-sequential"
        super().__init__(classes=classes)
        self.tool_type = tool_type
        self.target = target
        self.result_text = result_text
        self.icon_name = tool_type
        self.header_label = Label("", classes="tool-header")

    def compose(self) -> ComposeResult:
        yield self.header_label

    def on_mount(self) -> None:
        self.render_header()

    def set_result(self, result_text: str) -> None:
        self.result_text = result_text.strip()
        self.render_header()

    def render_header(self) -> None:
        self.header_label.update(f"⚙ [bold]{self.icon_name}[/bold]({self.target})")


class WelcomeWidget(Vertical):
    """Приветствие по центру главного экрана"""
    can_focus = False

    FULL_BANNER = (
        "   _       _                 _                 \n"
        "  (_)     | |               | |                \n"
        "   _  ___ | |__  _ __  ___ _| |_ ___  _ __     \n"
        "  | |/ _ \\| '_ \\| '_ \\/ __|_   _/ _ \\| '_ \\    \n"
        "  | | (_) | | | | | | \\__ \\ | || (_) | | | |   \n"
        "  | |\\___/|_| |_|_| |_|___/  \\__\\___/|_| |_|   \n"
        " /_/                                           "
    )

    def compose(self) -> ComposeResult:
        yield Static(self.FULL_BANNER, id="welcome-logo")

    def _update_banner_for_size(self, width: int) -> None:
        try:
            logo = self.query_one("#welcome-logo", Static)
            if width < 52:
                logo.update("[bold #ffffff]johnston[/bold #ffffff]")
            else:
                logo.update(self.FULL_BANNER)
        except Exception:
            pass

    def on_mount(self) -> None:
        if self.app and self.app.size.width > 0:
            self._update_banner_for_size(self.app.size.width)

    def on_resize(self, event) -> None:
        self._update_banner_for_size(event.size.width)


class ChatView(VerticalScroll):
    """Скроллируемый поток чата"""
    can_focus = False

    def on_mount(self) -> None:
        self.check_welcome()

    def clear_welcome(self) -> None:
        for w in self.query(WelcomeWidget):
            w.remove()

    def check_welcome(self) -> None:
        msg_children = [c for c in self.children if not isinstance(c, WelcomeWidget)]
        welcome = list(self.query(WelcomeWidget))
        if not msg_children:
            if not welcome:
                self.mount(WelcomeWidget())
        else:
            for w in welcome:
                w.remove()

    async def add_user_message(self, text: str) -> UserMessage:
        self.clear_welcome()
        msg = UserMessage(text)
        await self.mount(msg)
        self.scroll_end(animate=True)
        return msg

    async def add_bot_message(self) -> BotMessage:
        self.clear_welcome()
        msg = BotMessage()
        await self.mount(msg)
        self.scroll_end(animate=True)
        return msg

    async def add_thinking_widget(self, thinking_text: str = "Thinking...") -> ThinkingWidget:
        self.clear_welcome()
        widget = ThinkingWidget(thinking_text)
        await self.mount(widget)
        self.scroll_end(animate=True)
        return widget

    async def add_tool_call(self, tool_type: str, target: str, result_text: str = "") -> ToolCallWidget:
        self.clear_welcome()
        is_seq = bool(self.children and isinstance(self.children[-1], ToolCallWidget))
        widget = ToolCallWidget(tool_type, target, result_text=result_text, is_sequential=is_seq)
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
        self.check_welcome()
