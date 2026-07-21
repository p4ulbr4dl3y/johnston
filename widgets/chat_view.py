from textual.app import ComposeResult
from textual.containers import VerticalScroll, Vertical
from textual.widgets import Static, Markdown, Label
from textual.reactive import reactive
from textual import events
import os

class UserMessage(Static):
    """Сообщение пользователя"""
    can_focus = False

    def __init__(self, content: str):
        self.raw_text = content
        super().__init__(content, classes="user-msg")

    def on_click(self, event: events.Click) -> None:
        if getattr(self.app, "selection_copy_active", False):
            return
        try:
            chat_input = self.app.query_one("#message-input")
            chat_input.load_text(self.raw_text)
            chat_input.focus()
            lines = chat_input.text.split("\n")
            chat_input.move_cursor((len(lines) - 1, len(lines[-1])))
            self.app.notify("Message loaded into input field!")
        except Exception as e:
            self.app.notify(f"Load failed: {e}", severity="error")


class BotMessage(Vertical):
    """Сообщение ИИ с полным рендерингом Markdown"""
    can_focus = False
    content = reactive("")

    def __init__(self, persona_name: str = "AI"):
        super().__init__(classes="bot-msg")
        self.md_widget = Markdown("")

    def compose(self) -> ComposeResult:
        yield self.md_widget

    def watch_content(self, new_content: str) -> None:
        self.md_widget.update(new_content)

    def on_click(self, event: events.Click) -> None:
        if getattr(self.app, "selection_copy_active", False):
            return
        try:
            if self.content:
                chat_input = self.app.query_one("#message-input")
                chat_input.load_text(self.content)
                chat_input.focus()
                lines = chat_input.text.split("\n")
                chat_input.move_cursor((len(lines) - 1, len(lines[-1])))
                self.app.notify("Message loaded into input field!")
        except Exception as e:
            self.app.notify(f"Load failed: {e}", severity="error")


class ThinkingWidget(Vertical):
    """Виджет думания с поддержкой Markdown при разворачивании"""
    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, thinking_text: str = "Thinking..."):
        super().__init__(classes="thinking-widget thinking-active")
        self.thinking_text = thinking_text
        self.duration_seconds = 0.0
        self.is_thinking = True
        self.is_expanded = False
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
    """Отдельный разворачиваемый виджет вызова инструмента (Create, Read, Edit, Bash)"""
    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, tool_type: str, target: str, result_text: str = ""):
        super().__init__(classes=f"tool-call tool-{tool_type.lower()}")
        self.tool_type = tool_type
        self.target = target
        self.result_text = result_text
        self.is_expanded = False

        self.icon_name = tool_type
        
        self.header_label = Label("", classes="tool-header")
        self.md_widget = Markdown("")
        self.diff_widget = Static("", classes="tool-diff-view")

    def compose(self) -> ComposeResult:
        yield self.header_label
        yield self.md_widget
        yield self.diff_widget

    def on_mount(self) -> None:
        self.md_widget.display = False
        self.diff_widget.display = False
        self.render_header()
        if self.result_text:
            self.set_result(self.result_text)

    def set_result(self, result_text: str) -> None:
        self.result_text = result_text.strip()
        self.render_header()

    def on_click(self, event: events.Click) -> None:
        if getattr(self.app, "selection_copy_active", False):
            return
        try:
            if self.result_text:
                self.app.copy_to_clipboard(self.result_text)
                self.app.notify(f"{self.tool_type} result copied to clipboard!")
        except Exception as e:
            self.app.notify(f"Copy failed: {e}", severity="error")
        
        if not self.result_text:
            return

        if self.tool_type == "Edit":
            # Красивый гитоподобный дифф с цветными полосами
            from rich.text import Text
            t = Text()
            lines = self.result_text.splitlines()
            for line in lines:
                if line.startswith("+"):
                    t.append(line + "\n", style="#10b981 on #022c22")
                elif line.startswith("-"):
                    t.append(line + "\n", style="#ef4444 on #450a0a")
                elif line.startswith("@@"):
                    t.append(line + "\n", style="#00ffd1")
                else:
                    t.append(line + "\n", style="#a1a1aa")
            self.diff_widget.update(t)
            
            if self.is_expanded:
                self.diff_widget.display = True
                self.md_widget.display = False
        else:
            if self.tool_type == "Bash":
                formatted_md = f"```bash\n{self.result_text}\n```"
            elif self.tool_type == "Create":
                ext = os.path.splitext(self.target)[1].lstrip(".")
                formatted_md = f"```{ext}\n{self.result_text}\n```"
            else:
                formatted_md = self.result_text
            self.md_widget.update(formatted_md)
            
            if self.is_expanded:
                self.md_widget.display = True
                self.diff_widget.display = False

    def render_header(self) -> None:
        self.header_label.update(f"⚙ [bold]{self.icon_name}[/bold]({self.target})")


class ChatView(VerticalScroll):
    """Скроллируемый поток чата"""
    can_focus = False

    async def add_user_message(self, text: str) -> UserMessage:
        msg = UserMessage(text)
        await self.mount(msg)
        self.scroll_end(animate=True)
        return msg

    async def add_bot_message(self, persona_name: str = "AI") -> BotMessage:
        msg = BotMessage(persona_name=persona_name)
        await self.mount(msg)
        self.scroll_end(animate=True)
        return msg

    async def add_thinking_widget(self, thinking_text: str = "Thinking...") -> ThinkingWidget:
        widget = ThinkingWidget(thinking_text)
        await self.mount(widget)
        self.scroll_end(animate=True)
        return widget

    async def add_tool_call(self, tool_type: str, target: str, result_text: str = "") -> ToolCallWidget:
        widget = ToolCallWidget(tool_type, target, result_text=result_text)
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
