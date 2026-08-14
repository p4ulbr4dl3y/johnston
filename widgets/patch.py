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

    Screen._forward_event = _safe_forward_event

    from widgets.chat_markdown import _apply_chat_markdown_patches

    _apply_chat_markdown_patches()
