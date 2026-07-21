from widgets.screens.base_selection import BaseSelectionScreen

class RewindScreen(BaseSelectionScreen[int]):
    """Modal rollback screen (/rewind)"""

    def __init__(self, user_messages: list[tuple[int, str]]):
        options = [
            f"{text[:50]}..." if len(text) > 50 else text
            for _, text in user_messages
        ]
        items = [idx for idx, _ in user_messages]
        default_val = items[-1] if items else -1
        super().__init__(
            title="### ↺ **Select message to rollback to**",
            options=options,
            items=items,
            default_value=default_val
        )
