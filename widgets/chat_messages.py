import asyncio

from rich.markdown import Markdown as RichMarkdown
from rich.rule import Rule
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Label, Markdown, Static

from widgets.chat_markdown import _handle_markdown_task_done, clean_markdown_for_rendering, safe_update_markdown


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
    """AI message with full Markdown rendering"""

    can_focus = False
    content = reactive("")
    MAX_INTERACTIVE_MARKDOWN_CHARS = 12000
    MAX_INTERACTIVE_MARKDOWN_LINES = 250

    def __init__(self):
        super().__init__(classes="bot-msg")
        self.stream_widget = Static("", markup=False, classes="bot-msg-stream")
        self.md_widget = Markdown("")
        self._streaming = False
        self._stream_update_scheduled = False
        self._stream_update_handle: asyncio.TimerHandle | None = None
        self._suppress_content_watch = False
        self._pending_markdown_content: str | None = None
        self._markdown_render_task: asyncio.Task | None = None

    def compose(self) -> ComposeResult:
        yield self.stream_widget
        yield self.md_widget

    def on_mount(self) -> None:
        self.stream_widget.display = False

    def watch_content(self, new_content: str) -> None:
        if self._suppress_content_watch:
            return
        if self._streaming:
            self._schedule_stream_update()
        else:
            self._schedule_markdown_render(new_content)

    def set_stream_content(self, content: str) -> None:
        """Update streaming text without rebuilding the Markdown widget tree."""
        if not self._streaming:
            self._streaming = True
            self.stream_widget.display = True
            self.md_widget.display = False
        self.content = content

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
        self.stream_widget.update(self.content)
        self._scroll_if_needed()

    async def set_final_content(self, content: str) -> None:
        """Render final Markdown once and wait until its widget tree is mounted."""
        self._suppress_content_watch = True
        try:
            self.content = content
        finally:
            self._suppress_content_watch = False
        if self._stream_update_handle is not None:
            self._stream_update_handle.cancel()
            self._stream_update_handle = None
        self._stream_update_scheduled = False
        task = self._markdown_render_task
        if task is not None and task is not asyncio.current_task() and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._pending_markdown_content = None
        cleaned = clean_markdown_for_rendering(content)
        if (
            len(cleaned) > self.MAX_INTERACTIVE_MARKDOWN_CHARS
            or cleaned.count("\n") > self.MAX_INTERACTIVE_MARKDOWN_LINES
        ):
            self.stream_widget.update(RichMarkdown(cleaned))
            self._streaming = False
            self.stream_widget.display = True
            self.md_widget.display = False
            self._scroll_if_needed()
            return
        await self._render_markdown(content)
        self._streaming = False
        self.stream_widget.display = False
        self.md_widget.display = True
        self._scroll_if_needed()

    async def finalize_stream(self, content: str | None = None) -> None:
        await self.set_final_content(self.content if content is None else content)

    def _schedule_markdown_render(self, content: str) -> None:
        """Coalesce compatibility assignments so only one Markdown render runs."""
        self._pending_markdown_content = content
        if self._markdown_render_task is not None and not self._markdown_render_task.done():
            return
        try:
            self._markdown_render_task = asyncio.create_task(self._drain_markdown_render())
            self._markdown_render_task.add_done_callback(_handle_markdown_task_done)
        except RuntimeError:
            safe_update_markdown(self.md_widget, content, on_done=self._scroll_if_needed)

    async def _drain_markdown_render(self) -> None:
        while self._pending_markdown_content is not None:
            content = self._pending_markdown_content
            self._pending_markdown_content = None
            await self._render_markdown(content)
        self._scroll_if_needed()

    async def _render_markdown(self, content: str) -> None:
        if not self.md_widget.is_attached:
            return
        cleaned = clean_markdown_for_rendering(content)
        try:
            await self.md_widget.update(cleaned)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

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
        task = self._markdown_render_task
        if task is not None and not task.done():
            task.cancel()


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
            self.thinking_text = content
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
        try:
            if hasattr(self, "screen") and type(self.screen).__name__ == "SubagentViewScreen":
                return False
        except Exception:
            pass
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
