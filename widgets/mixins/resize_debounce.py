"""Debounced resize handling for widgets that re-render custom content.

Consolidates the previously copy-pasted pattern (``_resize_timer`` /
``_last_resize_size`` / 0.15s ``set_timer``) from StatusFooter,
SubagentStatusFooter and SubagentHeader into one mixin. Timer attributes are
class-level defaults so no ``__init__`` coordination is required.

Subclasses override :meth:`render_for_size` and call
:meth:`cancel_resize_timer` from their ``on_unmount``.
"""

from __future__ import annotations

from typing import Any

from textual.timer import Timer


class ResizeDebounceMixin:
    """Collapse resize event storms into a single deferred re-render."""

    RESIZE_DEBOUNCE_SECONDS: float = 0.15

    _resize_timer: Timer | None = None
    _last_resize_size: Any = None

    def on_resize(self, event) -> None:
        size = getattr(event, "size", None)
        if size is not None and size == self._last_resize_size:
            return
        self._last_resize_size = size
        self.cancel_resize_timer()
        self._resize_timer = self.set_timer(self.RESIZE_DEBOUNCE_SECONDS, self._debounced_resize)

    def _debounced_resize(self) -> None:
        """Timer callback: clear the handle, then let the subclass re-render."""
        self._resize_timer = None
        self.render_for_size()

    def render_for_size(self) -> None:
        """Re-render content for the current terminal size. Override in subclass."""
        raise NotImplementedError(f"{type(self).__name__} must implement render_for_size()")

    def cancel_resize_timer(self) -> None:
        """Stop the pending debounce timer if any; safe to call repeatedly."""
        timer, self._resize_timer = self._resize_timer, None
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass
