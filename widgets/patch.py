from textual.screen import Screen
from textual.widget import Widget


def apply_textual_patches() -> None:
    """Applies patches to Textual base classes (allow_select for nested widgets and safe selection forwarding)"""

    def _new_allow_select(self) -> bool:
        node = self
        while node is not None:
            if not getattr(node, "ALLOW_SELECT", True):
                return False
            node = node.parent
        return True

    Widget.allow_select = property(_new_allow_select)

    original_forward_event = getattr(Screen, "_original_forward_event", Screen._forward_event)
    Screen._original_forward_event = original_forward_event

    def _safe_forward_event(self, event):
        try:
            original_forward_event(self, event)
        except AttributeError as err:
            if "has no attribute 'region'" in str(err) or "has no attribute 'scroll_offset'" in str(err):
                self._select_state = None
            else:
                raise

    from rich.console import Console
    from textual.selection import Selection
    from textual.widgets import Static

    _old_static_get_selection = getattr(Static, "_original_get_selection", Static.get_selection)
    Static._original_get_selection = _old_static_get_selection

    def _new_static_get_selection(self: Static, selection: Selection) -> tuple[str, str] | None:
        result = _old_static_get_selection(self, selection)
        if result is not None:
            return result
        try:
            visual = self._render()
            renderable = getattr(visual, "_renderable", visual)
            console = getattr(getattr(self, "app", None), "console", None) or Console()
            width = getattr(getattr(self, "size", None), "width", 0) or getattr(console, "width", 80)
            lines = []
            for line in console.render_lines(renderable, console.options.update(width=width, height=None, justify="left")):
                lines.append("".join(seg.text for seg in line).rstrip())
            text = "\n".join(lines)
            extracted = selection.extract(text)
            return (extracted, "\n") if extracted else None
        except Exception:
            return None

    Static.get_selection = _new_static_get_selection

    from widgets.chat_markdown import _apply_chat_markdown_patches

    _apply_chat_markdown_patches()
