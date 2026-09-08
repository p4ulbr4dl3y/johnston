"""Hint timing, debounce, and sibling coordination mixin for ToolCallWidget."""
from __future__ import annotations

import asyncio


class ToolCallHintsMixin:
    """Hint debouncing, active hint coordination with parent, and sibling spacing."""

    HINT_DEBOUNCE_SECONDS: float = 0.25

    def set_show_hints(self, show: bool) -> None:
        if getattr(self, "_show_hints", False) == show:
            return
        self._show_hints = show
        self.render_header()

    def _schedule_hint_timer(self) -> None:
        self._cancel_hint_timer()
        if not self.is_expandable():
            self._show_hints = False
            return
        parent = getattr(self, "parent", None)
        if parent is not None and getattr(parent, "_has_active_hints", False):
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
        if getattr(self, "status", None) == "running" and self.is_expandable():
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

    def _update_next_sibling_spacing(self) -> None:
        parent = getattr(self, "parent", None)
        if not parent:
            return
        raw = getattr(parent, "children", None)
        if raw is None or not hasattr(raw, "__iter__") or type(raw).__name__ == "MagicMock":
            return
        children = list(raw)
        try:
            idx = children.index(self)
        except ValueError:
            return
        for child in children[idx + 1 :]:
            if getattr(child, "_pruning", False):
                continue
            from johnston_tui.presentation.widgets.chat_messages import BotMessage

            if isinstance(child, BotMessage):
                c_str = child.raw_text if hasattr(child, "raw_text") else getattr(child, "content", "")
                if not (c_str or "").strip():
                    continue
            from johnston_tui.chat_toolcall import ToolCallWidget

            if isinstance(child, ToolCallWidget):
                child.is_sequential = True
                if getattr(self, "is_expanded", False):
                    child.remove_class("tool-sequential")
                else:
                    child.add_class("tool-sequential")
            break

    def _sync_sequential_with_prev(self) -> None:
        parent = getattr(self, "parent", None)
        if not parent:
            return
        raw = getattr(parent, "children", None)
        if raw is None or not hasattr(raw, "__iter__") or type(raw).__name__ == "MagicMock":
            return
        children = list(raw)
        try:
            idx = children.index(self)
        except ValueError:
            return
        for child in reversed(children[:idx]):
            if getattr(child, "_pruning", False):
                continue
            from johnston_tui.presentation.widgets.chat_messages import BotMessage

            if isinstance(child, BotMessage):
                c_str = child.raw_text if hasattr(child, "raw_text") else getattr(child, "content", "")
                if not (c_str or "").strip():
                    continue
            from johnston_tui.chat_toolcall import ToolCallWidget

            if isinstance(child, ToolCallWidget):
                self.is_sequential = True
                if getattr(child, "is_expanded", False):
                    self.remove_class("tool-sequential")
                else:
                    self.add_class("tool-sequential")
            else:
                self.is_sequential = False
                self.remove_class("tool-sequential")
            break
