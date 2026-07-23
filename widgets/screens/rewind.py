from widgets.screens.base_selection import BaseSelectionScreen


class RewindScreen(BaseSelectionScreen[int]):
    """Modal rollback screen (/rewind)"""

    def __init__(self, user_messages: list[tuple[int, str]]):
        options = []
        for _, text in user_messages:
            clean = " ".join(text.replace("\n", " ").replace("\r", " ").split())
            opt = f"{clean[:50]}..." if len(clean) > 50 else clean
            options.append(opt or "(empty message)")

        items = [idx for idx, _ in user_messages]
        default_val = items[-1] if items else -1
        super().__init__(
            title="### **Select message to rollback to**",
            options=options,
            items=items,
            default_value=default_val
        )

