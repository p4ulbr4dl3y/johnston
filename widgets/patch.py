from textual.widget import Widget


def apply_textual_patches() -> None:
    """Applies patches to Textual base classes (allow_select for nested widgets)"""
    def _new_allow_select(self) -> bool:
        node = self
        while node is not None:
            if not getattr(node, "ALLOW_SELECT", True):
                return False
            node = node.parent
        return True

    Widget.allow_select = property(_new_allow_select)
