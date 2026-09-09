import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)


class ChatViewHintsMixin:
    """Hotkey hints management and fading timers for ChatView."""

    HINT_FADE_SECONDS: float = 1.5

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._active_hint_widget = None
        self._has_active_hints = False
        self._hint_fade_handle = None
        self.HINT_FADE_SECONDS = 1.5

    def activate_hint(self, widget: Any) -> None:
        """Activate hint on the given widget and clear it from the previously active one."""
        self._cancel_hint_fade_timer()
        if self._active_hint_widget and self._active_hint_widget != widget:
            if hasattr(self._active_hint_widget, "set_show_hints"):
                self._active_hint_widget.set_show_hints(False)
        self._active_hint_widget = widget
        self._has_active_hints = True
        if hasattr(widget, "set_show_hints"):
            widget.set_show_hints(True)

    def on_widget_finished(self, widget: Any) -> None:
        """Handle completion of an expandable widget, starting the smooth fade timer."""
        if self._active_hint_widget == widget:
            if getattr(widget, "is_expandable", lambda: False)():
                if hasattr(widget, "_show_hints"):
                    widget._show_hints = True
                if hasattr(widget, "render_header"):
                    widget.render_header()
                self._start_hint_fade_timer()
            else:
                if hasattr(widget, "set_show_hints"):
                    widget.set_show_hints(False)
                self._active_hint_widget = None
                self._start_hint_fade_timer()

    def _cancel_hint_fade_timer(self) -> None:
        if self._hint_fade_handle is not None:
            try:
                self._hint_fade_handle.cancel()
            except Exception:
                pass
            self._hint_fade_handle = None

    def _start_hint_fade_timer(self, delay: float | None = None) -> None:
        self._cancel_hint_fade_timer()
        timeout = delay if delay is not None else self.HINT_FADE_SECONDS
        try:
            loop = asyncio.get_running_loop()
            self._hint_fade_handle = loop.call_later(timeout, self._on_hint_fade_timeout)
        except RuntimeError:
            self.clear_active_hints(immediate=True)

    def _on_hint_fade_timeout(self) -> None:
        self._hint_fade_handle = None
        self.clear_active_hints(immediate=True)

    def clear_active_hints(self, immediate: bool = False) -> None:
        """Clear active hotkey hints from tool/thinking widgets."""
        if immediate:
            self._cancel_hint_fade_timer()
            if self._active_hint_widget is not None:
                if hasattr(self._active_hint_widget, "set_show_hints"):
                    self._active_hint_widget.set_show_hints(False)
                self._active_hint_widget = None
            self._has_active_hints = False
        else:
            self._start_hint_fade_timer()

    def on_generation_finished(self) -> None:
        """Called when turn generation completes."""
        if self._active_hint_widget is not None:
            self._start_hint_fade_timer()
        else:
            self._has_active_hints = False

    def on_unmount(self) -> None:
        self._cancel_hint_fade_timer()


__all__ = ["ChatViewHintsMixin"]
