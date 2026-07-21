from textual.widget import Widget

def apply_textual_patches() -> None:
    """Применяет расширения над базом классами Textual (allow_select для вложенных виджетов)"""
    def _new_allow_select(self) -> bool:
        node = self
        while node is not None:
            if not getattr(node, "ALLOW_SELECT", True):
                return False
            node = node.parent
        return True

    Widget.allow_select = property(_new_allow_select)
