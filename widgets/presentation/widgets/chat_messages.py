import asyncio
import logging

from rich.rule import Rule
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.reactive import reactive
from textual.widgets import Label, Markdown, Static

from core.infrastructure.config.settings import get_settings
from widgets.presentation.widgets.chat_markdown import (
    _handle_markdown_task_done,
    prepare_markdown_text,
    safe_update_markdown,
)
from widgets.utils.row_format import ellipsize

logger = logging.getLogger(__name__)


def _clean_divider_title(title: str, max_len: int = 100) -> str:
    cleaned = " ".join((title or "").split())
    return ellipsize(cleaned, max_len)


class EventDivider(Static):
    """Full-width centered divider for session events (compaction, interruption, etc)"""

    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, title: str = "Session Compacted"):
        cleaned = _clean_divider_title(title)
        self.divider_title = cleaned
        super().__init__(Rule(cleaned, style="dim"), classes="event-divider")

    def update_title(self, title: str) -> None:
        cleaned = _clean_divider_title(title)
        self.divider_title = cleaned
        self.update(Rule(cleaned, style="dim"))


class ErrorMessage(Static):
    """Error callout message block with copy support"""

    can_focus = False
    ALLOW_SELECT = True

    def __init__(self, content: str | Text = "", markup: bool = False):
        if isinstance(content, Text):
            self.raw_text = content.plain
            renderable = content
        else:
            text_str = str(content or "")
            self.raw_text = text_str
            renderable = text_str
        super().__init__(renderable, markup=markup, classes="error-msg")


class UserMessageAttachment(Static):
    """Attachment footnote for UserMessage, unselectable so prompt copy stays clean"""

    can_focus = False
    ALLOW_SELECT = False


class UserMessagePrefix(Static):
    """Prompt chevron prefix for UserMessage, unselectable"""

    can_focus = False
    ALLOW_SELECT = False


class UserMessage(Horizontal):
    """User message"""

    can_focus = False

    def __init__(
        self,
        content: str | Text = "",
        attachment_text: str = "",
        markup: bool = False,
        is_first: bool = False,
    ):
        if isinstance(content, Text):
            user_str = content.plain
            renderable_content = content
        else:
            user_str = str(content or "")
            renderable_content = user_str

        att_str = str(attachment_text or "")
        if att_str and user_str:
            self.raw_text = f"{user_str}\n{att_str}"
        elif att_str:
            self.raw_text = att_str
        else:
            self.raw_text = user_str

        is_shell = user_str.startswith("!")
        prefix_char = "! " if is_shell else "❯ "
        prefix_cls = "user-msg-prefix user-msg-prefix-shell" if is_shell else "user-msg-prefix"
        prefix = UserMessagePrefix(prefix_char, markup=False, classes=prefix_cls)

        bubble_content = user_str[1:].lstrip() if (is_shell and not isinstance(content, Text)) else renderable_content

        if att_str:
            bubble = Vertical(
                Static(bubble_content, markup=markup, classes="user-msg-text"),
                UserMessageAttachment(att_str, markup=False, classes="user-msg-att"),
                classes="user-msg-bubble",
            )
        else:
            bubble = Static(bubble_content, markup=markup, classes="user-msg-bubble")

        classes = "user-msg user-msg-first" if is_first else "user-msg"
        self.prefix_widget = prefix
        self.bubble_widget = bubble
        super().__init__(prefix, bubble, classes=classes)


def scroll_parent_if_needed(widget, force: bool = False) -> None:
    """Stick the scrollable parent to the bottom after a content update.

    Follows only while the user is at the bottom (see ``ChatView._auto_follow``);
    an upward wheel tick pauses follow until the user returns to the bottom.
    Position is checked when scheduling. Deferred callbacks run *after* the
    layout refresh has already grown the content, so there ``is_at_bottom``
    would be false exactly when following matters — those callbacks therefore
    re-check user intent only (``_auto_follow``/``_is_loading_session``), never
    position.
    """
    try:
        parent = getattr(widget, "parent", None)
        if isinstance(parent, VerticalScroll):
            is_loading = getattr(parent, "_is_loading_session", False) or getattr(parent, "_is_loading_older", False)
            auto_follow = getattr(parent, "_auto_follow", True)
            should_schedule = not is_loading and (
                force or (auto_follow and getattr(parent, "is_at_bottom", lambda: True)())
            )
            if should_schedule and (not getattr(parent, "_scroll_pending", False) or force):
                parent._scroll_pending = True

                def _intent_active() -> bool:
                    return (
                        getattr(parent, "_auto_follow", True)
                        and not getattr(parent, "_is_loading_session", False)
                        and not getattr(parent, "_is_loading_older", False)
                    )

                def _settle_rescroll():
                    try:
                        # Layout may have grown content again; re-stick unless
                        # the user scrolled away in the meantime.
                        if _intent_active():
                            parent.scroll_end(animate=False)
                    except Exception:
                        logger.debug("Settle autoscroll failed", exc_info=True)

                def _do_scroll():
                    try:
                        parent._scroll_pending = False
                        if _intent_active():
                            parent.scroll_end(animate=False)
                            if hasattr(parent, "call_after_refresh"):
                                parent.call_after_refresh(_settle_rescroll)
                    except Exception:
                        logger.debug("Deferred autoscroll failed", exc_info=True)

                parent.call_after_refresh(_do_scroll)
    except Exception:
        logger.debug("Autoscroll dispatch failed", exc_info=True)


def scroll_parent_to_widget(widget, top: bool = False) -> None:
    try:
        parent = getattr(widget, "parent", None)
        if isinstance(parent, VerticalScroll):
            is_loading = getattr(parent, "_is_loading_session", False) or getattr(parent, "_is_loading_older", False)
            if not is_loading:
                def _do_scroll():
                    try:
                        if hasattr(parent, "scroll_to_widget"):
                            parent.scroll_to_widget(widget, top=top, animate=False)
                            if hasattr(parent, "call_after_refresh"):
                                parent.call_after_refresh(
                                    lambda: parent.scroll_to_widget(widget, top=top, animate=False)
                                )
                    except Exception:
                        logger.debug("Deferred scroll_to_widget failed", exc_info=True)

                parent.call_after_refresh(_do_scroll)
    except Exception:
        logger.debug("scroll_to_widget dispatch failed", exc_info=True)


class BotMessage(Vertical):
    """AI message with streaming Static and rich interactive Textual Markdown rendering"""

    can_focus = False
    content = reactive("")

    def __init__(self):
        super().__init__(classes="bot-msg")
        self.stream_widget = Static("", markup=False, classes="bot-msg-stream")
        self.md_widget = Markdown("", classes="bot-msg-md")
        self._streaming = False
        self._stream_update_scheduled = False
        self._stream_update_handle: asyncio.TimerHandle | None = None
        self._suppress_content_watch = False
        self._markdown_render_task: asyncio.Task | None = None
        self._pending_markdown_content: str | None = None
        self._stream_parts: list[str] = []
        self._joined_content: str | None = None

    def compose(self) -> ComposeResult:
        yield self.stream_widget
        yield self.md_widget

    def on_mount(self) -> None:
        if self.content:
            self.stream_widget.display = False
            self.md_widget.display = True
        else:
            self.stream_widget.display = True
            self.md_widget.display = False

    def watch_content(self, new_content: str) -> None:
        if self._suppress_content_watch:
            return
        if self._streaming:
            self._schedule_stream_update()
        else:
            self._schedule_markdown_render(new_content)

    def append_stream_content(self, content: str) -> None:
        """Append a streaming delta to the message text."""
        if not self._streaming:
            self._streaming = True
            self.stream_widget.display = True
            self.md_widget.display = False
        self._stream_parts.append(content)
        self._joined_content = None
        self._schedule_stream_update()

    def set_stream_content(self, content: str) -> None:
        """Replace the streaming text with full content (no Markdown rebuild)."""
        if not self._streaming:
            self._streaming = True
            self.stream_widget.display = True
            self.md_widget.display = False
        self._stream_parts = [content]
        self._joined_content = None
        self._schedule_stream_update()

    def _join_stream_content(self) -> str:
        """Join pending stream parts into a single string (lazy-cached)."""
        if self._joined_content is None:
            self._joined_content = "".join(self._stream_parts)
        return self._joined_content

    async def reset_stream(self) -> None:
        """Clear partial streamed text on retry so the new attempt starts blank."""
        self._streaming = False
        self._stream_parts = []
        self._joined_content = None
        self._suppress_content_watch = True
        try:
            self.content = ""
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
        try:
            self.stream_widget.update("")
        except Exception:
            pass
        self.stream_widget.display = False
        self.md_widget.display = False

    def _schedule_stream_update(self) -> None:
        if self._stream_update_scheduled:
            return
        self._stream_update_scheduled = True
        try:
            self._stream_update_handle = asyncio.get_running_loop().call_later(get_settings().ui.stream_flush_interval, self._flush_stream_update)
        except RuntimeError:
            self._flush_stream_update()

    def _flush_stream_update(self) -> None:
        self._stream_update_scheduled = False
        self._stream_update_handle = None
        try:
            text = self._join_stream_content()
            self._suppress_content_watch = True
            try:
                self.content = text
            finally:
                self._suppress_content_watch = False
            if text != getattr(self, "_last_rendered_stream_text", None):
                self.stream_widget.update(text)
                self._last_rendered_stream_text = text
                self._scroll_if_needed()
        except Exception:
            logger.debug("Stream flush failed", exc_info=True)

    def flush_pending_stream(self) -> None:
        """Immediately render any still-pending debounced stream content."""
        if self._stream_parts:
            self._suppress_content_watch = True
            try:
                self.content = self._join_stream_content()
            finally:
                self._suppress_content_watch = False
        if self._stream_update_scheduled:
            self._flush_stream_update()

    async def set_final_content(self, content: str) -> None:
        """Render final Markdown once and wait until its widget tree is mounted."""
        self._stream_parts = [content]
        self._joined_content = content
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
        await self._render_markdown(content)
        self._streaming = False
        self.stream_widget.display = False
        self.md_widget.display = True
        self._scroll_if_needed()

    async def finalize_stream(self, content: str | None = None) -> None:
        if content is None:
            content = self._join_stream_content()
        self._suppress_content_watch = True
        try:
            self.content = content
        finally:
            self._suppress_content_watch = False
        await self.set_final_content(content)

    def _schedule_markdown_render(self, content: str) -> None:
        """Coalesce rapid content updates so only one Markdown render task runs at a time."""
        self._pending_markdown_content = content
        if self._markdown_render_task is not None and not self._markdown_render_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
            coro = self._drain_markdown_render()
            self._markdown_render_task = loop.create_task(coro)
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
        # Clean + pre-highlight code fences in a worker thread so mounting the
        # document never blocks the UI loop on pygments (highlight cache in
        # chat_markdown makes compose() cheap).
        try:
            dark = bool(getattr(self.app.current_theme, "dark", True))
        except Exception:
            dark = True
        cleaned = await asyncio.to_thread(prepare_markdown_text, content, dark)
        try:
            await self.md_widget.update(cleaned)
        except asyncio.CancelledError:
            raise
        except Exception:
            pass

    def _scroll_if_needed(self) -> None:
        scroll_parent_if_needed(self)

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
    HINT_DEBOUNCE_SECONDS: float = 0.25

    def __init__(self, thinking_text: str = ""):
        super().__init__(classes="thinking-widget thinking-active")
        initial = "" if thinking_text == "Thinking..." else thinking_text
        self._thinking_parts: list[str] = [initial] if initial else []
        self._cached_thinking_text: str | None = initial
        self.duration_seconds = 0.0
        self.is_thinking = True
        self.is_expanded = False
        self._update_scheduled = False
        self._update_handle: asyncio.TimerHandle | None = None
        self._show_hints = False
        self._hint_handle: asyncio.TimerHandle | None = None
        self._schedule_hint_timer()

        self.header_label = Label("", classes="thinking-header")
        self.content_widget = Static("", markup=False, classes="thinking-content")
        self.render_header()

    def set_show_hints(self, show: bool) -> None:
        if getattr(self, "_show_hints", False) == show:
            return
        self._show_hints = show
        self.render_header()

    def _schedule_hint_timer(self) -> None:
        self._cancel_hint_timer()
        parent = getattr(self, "parent", None)
        if parent is not None and getattr(parent, "_has_active_hints", False) and self.is_expandable():
            if hasattr(parent, "activate_hint"):
                parent.activate_hint(self)
                return
        self._show_hints = False
        try:
            loop = asyncio.get_running_loop()
            self._hint_handle = loop.call_later(self.HINT_DEBOUNCE_SECONDS, self._on_hint_timer)
        except RuntimeError:
            self._show_hints = True

    def _on_hint_timer(self) -> None:
        self._hint_handle = None
        if self.is_thinking:
            parent = getattr(self, "parent", None)
            if parent is not None and hasattr(parent, "activate_hint"):
                parent.activate_hint(self)
            else:
                self._show_hints = True
                self.render_header()

    def _cancel_hint_timer(self) -> None:
        if getattr(self, "_hint_handle", None) is not None:
            try:
                self._hint_handle.cancel()
            except Exception:
                pass
            self._hint_handle = None

    @property
    def thinking_text(self) -> str:
        if self._cached_thinking_text is None:
            self._cached_thinking_text = "".join(self._thinking_parts)
        return self._cached_thinking_text

    @thinking_text.setter
    def thinking_text(self, value: str) -> None:
        self._thinking_parts = [value] if value else []
        self._cached_thinking_text = value

    def compose(self) -> ComposeResult:
        yield self.header_label
        yield self.content_widget

    def on_mount(self) -> None:
        if self.is_expanded:
            if self.thinking_text:
                self.content_widget.update(self.thinking_text)
            self.content_widget.display = True
        else:
            self.content_widget.display = False
        if self.is_expandable():
            self.header_label.add_class("thinking-header-expandable")
        else:
            self.header_label.remove_class("thinking-header-expandable")
        if self.is_thinking and self.is_expandable():
            parent = getattr(self, "parent", None)
            if parent is not None and getattr(parent, "_has_active_hints", False):
                if hasattr(parent, "activate_hint"):
                    self._cancel_hint_timer()
                    parent.activate_hint(self)

    def _schedule_content_update(self) -> None:
        if self._update_scheduled or not self.is_expanded:
            return
        self._update_scheduled = True
        try:
            self._update_handle = asyncio.get_running_loop().call_later(get_settings().ui.stream_flush_interval, self._flush_content_update)
        except RuntimeError:
            self._flush_content_update()

    def _scroll_if_needed(self, force: bool = False) -> None:
        scroll_parent_if_needed(self, force=force)

    def _flush_content_update(self) -> None:
        self._update_scheduled = False
        self._update_handle = None
        if not self.is_expanded:
            return
        try:
            txt = self.thinking_text
            if txt != getattr(self, "_last_rendered_thinking", None):
                self.content_widget.update(txt)
                self._last_rendered_thinking = txt
                self._scroll_if_needed()
        except Exception:
            logger.debug("Thinking flush failed", exc_info=True)

    def update_thinking(self, content: str) -> None:
        if content and content != "Thinking...":
            self._thinking_parts.append(content)
            self._cached_thinking_text = None
            if self.is_expanded:
                self._schedule_content_update()

    def finish_thinking(self, duration: float, thinking_content: str = "") -> None:
        self.is_thinking = False
        self.duration_seconds = duration
        self._cancel_hint_timer()
        parent = getattr(self, "parent", None)
        if parent is not None and hasattr(parent, "on_widget_finished"):
            parent.on_widget_finished(self)
        else:
            self._show_hints = False
        if thinking_content and thinking_content != "Thinking...":
            self._thinking_parts = [thinking_content]
            self._cached_thinking_text = thinking_content
        if self._update_handle is not None:
            self._update_handle.cancel()
            self._update_handle = None
        self._update_scheduled = False
        self.remove_class("thinking-active")
        if self.is_expanded:
            self.content_widget.update(self.thinking_text or "")
            self._scroll_if_needed()
        self.render_collapsed()

    def render_header(self) -> None:
        if self.is_thinking:
            if getattr(self, "_show_hints", False):
                from widgets.presentation.widgets.footer_layout import get_theme_colors

                _, _, t_muted, _ = get_theme_colors()
                action = "to collapse" if self.is_expanded else "to expand"
                hint_str = f" [{t_muted}](ctrl+o {action})[/]"
            else:
                hint_str = ""
            self.header_label.update(f"Thinking...{hint_str}")
        else:
            dur_str = "<0.1" if self.duration_seconds < 0.1 else f"{self.duration_seconds:.1f}"
            self.header_label.update(f"Thought for {dur_str} sec")


    def render_collapsed(self) -> None:
        self.render_header()
        if not self.is_expanded:
            self.content_widget.display = False

    def on_click(self, event) -> None:
        if not self.is_expandable():
            return
        self.toggle_expanded()
        event.stop()

    def is_expandable(self) -> bool:
        return True

    def set_expanded(self, expanded: bool, scroll: bool = False) -> None:
        if not self.is_expandable():
            return
        if self.is_expanded == expanded:
            return
        self.is_expanded = expanded
        self.render_header()
        if self.is_expanded:
            if self.thinking_text:
                self.content_widget.update(self.thinking_text)
            self.content_widget.display = True
            if scroll:
                scroll_parent_to_widget(self, top=False)
        else:
            if self._update_handle is not None:
                self._update_handle.cancel()
                self._update_handle = None
            self._update_scheduled = False
            self.content_widget.display = False

    def toggle_expanded(self, scroll: bool = True) -> None:
        self.set_expanded(not self.is_expanded, scroll=scroll)

    def on_unmount(self) -> None:
        self._cancel_hint_timer()
        parent = getattr(self, "parent", None)
        if parent is not None and getattr(parent, "_active_hint_widget", None) is self:
            if hasattr(parent, "clear_active_hints"):
                parent.clear_active_hints(immediate=True)
        if self._update_handle is not None:
            self._update_handle.cancel()
            self._update_handle = None
