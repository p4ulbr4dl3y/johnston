import asyncio

from rich.markdown import Markdown as RichMarkdown
from rich.rule import Rule
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Label, Static

from widgets.chat_markdown import (
    CODE_THEME,
    _apply_chat_markdown_patches,
    clean_markdown_for_rendering,
)


class EventDivider(Static):
    """Full-width centered divider for session events (compaction, interruption, etc)"""

    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, title: str = "Session Compacted"):
        self.divider_title = title
        super().__init__(Rule(title, style="dim #71717a"), classes="event-divider")

    def update_title(self, title: str) -> None:
        self.divider_title = title
        self.update(Rule(title, style="dim #71717a"))


class UserMessage(Horizontal):
    """User message"""

    can_focus = False

    def __init__(self, content: str, markup: bool = False):
        self.raw_text = content
        super().__init__(Static(content, markup=markup, classes="user-msg-bubble"), classes="user-msg")


class BotMessage(Vertical):
    """AI message with Rich Markdown rendering"""

    can_focus = False
    content = reactive("")

    def __init__(self):
        super().__init__(classes="bot-msg")
        self.stream_widget = Static("", markup=False, classes="bot-msg-stream")
        self.md_widget = self.stream_widget
        self._streaming = False
        self._stream_update_scheduled = False
        self._stream_update_handle: asyncio.TimerHandle | None = None
        self._suppress_content_watch = False

    def compose(self) -> ComposeResult:
        yield self.stream_widget

    def on_mount(self) -> None:
        self.stream_widget.display = True

    def watch_content(self, new_content: str) -> None:
        if self._suppress_content_watch:
            return
        if self._streaming:
            self._schedule_stream_update()
        else:
            self._render_rich_content(new_content)

    def append_stream_content(self, content: str) -> None:
        """Append a streaming delta to the message text."""
        if not self._streaming:
            self._streaming = True
        self.content = self.content + content

    def set_stream_content(self, content: str) -> None:
        """Replace the streaming text with full content (no Markdown rebuild)."""
        if not self._streaming:
            self._streaming = True
        self.content = content

    async def reset_stream(self) -> None:
        """Clear partial streamed text on retry so the new attempt starts blank."""
        self._streaming = False
        self._suppress_content_watch = True
        try:
            self.content = ""
        finally:
            self._suppress_content_watch = False
        if self._stream_update_handle is not None:
            self._stream_update_handle.cancel()
            self._stream_update_handle = None
        self._stream_update_scheduled = False
        try:
            self.stream_widget.update("")
        except Exception:
            pass

    def _schedule_stream_update(self) -> None:
        if self._stream_update_scheduled:
            return
        self._stream_update_scheduled = True
        try:
            self._stream_update_handle = asyncio.get_running_loop().call_later(0.05, self._flush_stream_update)
        except RuntimeError:
            self._flush_stream_update()

    def _flush_stream_update(self) -> None:
        self._stream_update_scheduled = False
        self._stream_update_handle = None
        if not self.is_attached:
            return
        try:
            self.stream_widget.update(self.content)
            self._scroll_if_needed()
        except Exception:
            pass

    def flush_pending_stream(self) -> None:
        """Immediately render any still-pending debounced stream content."""
        if self._stream_update_scheduled:
            self._flush_stream_update()

    def _render_rich_content(self, content: str) -> None:
        cleaned = clean_markdown_for_rendering(content)
        if cleaned:
            _apply_chat_markdown_patches()
            self.stream_widget.update(RichMarkdown(cleaned, code_theme=CODE_THEME))
        else:
            self.stream_widget.update("")
        self._scroll_if_needed()

    async def set_final_content(self, content: str) -> None:
        """Render final Rich Markdown once and update view."""
        self._suppress_content_watch = True
        try:
            self.content = content
        finally:
            self._suppress_content_watch = False
        if self._stream_update_handle is not None:
            self._stream_update_handle.cancel()
            self._stream_update_handle = None
        self._stream_update_scheduled = False
        self._streaming = False
        self._render_rich_content(content)

    async def finalize_stream(self, content: str | None = None) -> None:
        await self.set_final_content(self.content if content is None else content)

    def _scroll_if_needed(self) -> None:
        try:
            if isinstance(self.parent, VerticalScroll):
                is_at_bot = getattr(self.parent, "is_at_bottom", lambda: True)()
                is_loading = getattr(self.parent, "_is_loading_session", False)
                if is_at_bot and not is_loading:
                    self.parent.call_after_refresh(self.parent.scroll_end, animate=False)
        except Exception:
            pass

    def on_unmount(self) -> None:
        if self._stream_update_handle is not None:
            self._stream_update_handle.cancel()
            self._stream_update_handle = None


class ThinkingWidget(Vertical):
    """Thinking widget with fast Static text expansion support"""

    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, thinking_text: str = ""):
        super().__init__(classes="thinking-widget thinking-active")
        self.thinking_text = "" if thinking_text == "Thinking..." else thinking_text
        self.duration_seconds = 0.0
        self.is_thinking = True
        self.is_expanded = False

        self.header_label = Label("Thinking...", classes="thinking-header")
        self.content_widget = Static("", markup=False, classes="thinking-content")

    def compose(self) -> ComposeResult:
        yield self.header_label
        yield self.content_widget

    def on_mount(self) -> None:
        self.content_widget.display = False
        if self.is_expandable():
            self.header_label.add_class("thinking-header-expandable")
        else:
            self.header_label.remove_class("thinking-header-expandable")

    def update_thinking(self, content: str) -> None:
        if content and content != "Thinking...":
            self.thinking_text = self.thinking_text + content
            if self.is_expanded:
                self.content_widget.update(self.thinking_text)

    def finish_thinking(self, duration: float, thinking_content: str = "") -> None:
        self.is_thinking = False
        self.duration_seconds = duration
        if thinking_content and thinking_content != "Thinking...":
            self.thinking_text = thinking_content
        self.remove_class("thinking-active")
        if self.is_expanded:
            self.content_widget.update(self.thinking_text or "")
        self.render_collapsed()

    def render_collapsed(self) -> None:
        self.header_label.update(f"Thought for {self.duration_seconds:.1f} sec")
        if not self.is_expanded:
            self.content_widget.display = False

    def on_click(self, event) -> None:
        if not self.is_expandable():
            return
        self.toggle_expanded()
        event.stop()

    def is_expandable(self) -> bool:
        return True

    def toggle_expanded(self) -> None:
        if not self.is_expandable():
            return
        self.is_expanded = not self.is_expanded
        if self.is_expanded:
            if self.thinking_text:
                self.content_widget.update(self.thinking_text)
            self.content_widget.display = True
        else:
            self.content_widget.display = False
