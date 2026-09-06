import asyncio
import logging
from typing import Any

from textual import events

from widgets.presentation.widgets.chat_welcome import WelcomeWidget

logger = logging.getLogger(__name__)


class ChatViewScrollMixin:
    """Scrolling mechanics, auto-follow bottom tracking, and viewport management."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # Bottom-follow intent. Cleared by an upward wheel tick, restored by
        # scrolling back to the bottom or by sending a new message.
        self._auto_follow = True

    def on_mouse_scroll_up(self, event: events.MouseScrollUp) -> None:
        # Pause bottom-follow as soon as the view has somewhere to scroll up;
        # keeps a single wheel tick from being undone by the next stream flush.
        if self.max_scroll_y > 0:
            self._auto_follow = False
        if getattr(self, "_is_loading_older", False) or getattr(self, "_is_loading_session", False):
            event.prevent_default()
            return
        if self.scroll_y <= getattr(self, "PAGINATION_THRESHOLD", 10) and (
            hasattr(self, "has_older_messages") and self.has_older_messages()
        ):
            self.load_older_messages()

    def on_mouse_scroll_down(self, event: events.MouseScrollDown) -> None:
        # The framework's own scroll for this tick runs after this handler;
        # defer the check so it sees the post-tick position.
        self.call_after_refresh(self._resume_follow_if_at_bottom)

    def _resume_follow_if_at_bottom(self) -> None:
        if self.is_at_bottom():
            self._auto_follow = True

    def is_at_bottom(self, threshold: int = 3) -> bool:
        """Returns True if scroll position is at or near the bottom of the container."""
        return (self.max_scroll_y - self.scroll_y) <= threshold

    def scroll_up(self, *args: Any, **kwargs: Any) -> None:
        """Scroll chat up and trigger pagination near top."""
        if self.max_scroll_y > 0:
            self._auto_follow = False
        if getattr(self, "_is_loading_older", False) or getattr(self, "_is_loading_session", False):
            return
        if self.scroll_y <= getattr(self, "PAGINATION_THRESHOLD", 10) and (
            hasattr(self, "has_older_messages") and self.has_older_messages()
        ):
            self.load_older_messages()
        super().scroll_up(*args, **kwargs)

    def scroll_page_up(self, *args: Any, **kwargs: Any) -> None:
        """Scroll page up, pausing auto-follow and triggering pagination near top."""
        if self.max_scroll_y > 0:
            self._auto_follow = False
        if getattr(self, "_is_loading_older", False) or getattr(self, "_is_loading_session", False):
            return
        if self.scroll_y <= getattr(self, "PAGINATION_THRESHOLD", 10) and (
            hasattr(self, "has_older_messages") and self.has_older_messages()
        ):
            self.load_older_messages()
            return
        super().scroll_page_up(*args, **kwargs)

    def scroll_up_page(self) -> None:
        """Scroll chat up by one page and pause auto-follow."""
        if self.max_scroll_y > 0:
            self._auto_follow = False
        if getattr(self, "_is_loading_older", False) or getattr(self, "_is_loading_session", False):
            return
        if self.scroll_y <= getattr(self, "PAGINATION_THRESHOLD", 10) and (
            hasattr(self, "has_older_messages") and self.has_older_messages()
        ):
            self.load_older_messages()
            return
        self.scroll_page_up(animate=False)

    def scroll_down_page(self) -> None:
        """Scroll chat down by one page and resume auto-follow if bottom reached."""
        self.scroll_page_down(animate=False)
        self.call_after_refresh(self._resume_follow_if_at_bottom)

    def scroll_to_top(self) -> None:
        """Scroll chat to top and pause auto-follow."""
        if self.max_scroll_y > 0:
            self._auto_follow = False
        if getattr(self, "_is_loading_older", False) or getattr(self, "_is_loading_session", False):
            return
        if hasattr(self, "has_older_messages") and self.has_older_messages():
            self.load_older_messages()
            return
        self.scroll_home(animate=False)

    def scroll_to_bottom(self) -> None:
        """Scroll chat to bottom and re-enable auto-follow."""
        self.scroll_end(animate=False)
        self._auto_follow = True

    async def _wait_until_attached(self, timeout: float = 0.5) -> None:
        try:
            loop = asyncio.get_running_loop()
            t0 = loop.time()
            # Detached barely ever happens on the hot path; when it does, wait
            # with a coarse increment so we don't run 100 empty wakeups at 5ms.
            while not self.is_attached and (loop.time() - t0 < timeout):
                await asyncio.sleep(0.02)
        except Exception:
            pass

    async def _mount_and_scroll(
        self,
        widget: Any,
        should_scroll: bool = True,
        animate: bool = False,
        before: Any = None,
    ) -> Any:
        """Mount ``widget`` and optionally snap to the bottom.

        Auto-follow scrolls are always instant: animated scrolls get superseded
        by the next debounced stream flush (~50ms) and leave the tail jittering.
        """
        if getattr(self, "_has_welcome", False) or any(isinstance(c, WelcomeWidget) for c in self.children):
            if hasattr(self, "clear_welcome"):
                self.clear_welcome()
        if not self.is_attached:
            await self._wait_until_attached()
        if before is not None and getattr(self, "_is_loading_older", False):
            try:
                widget.styles.display = "none"
            except Exception:
                pass
        if before is not None:
            await self.mount(widget, before=before)
        else:
            await self.mount(widget)
        if should_scroll and before is None:
            self.call_after_refresh(self.scroll_end, animate=animate)
        return widget


__all__ = ["ChatViewScrollMixin"]
