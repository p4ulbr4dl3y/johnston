from widgets.screens.base_selection import BaseSelectionScreen


class RewindScreen(BaseSelectionScreen[int]):
    """Modal rollback screen (/rewind)"""

    def __init__(self, user_messages: list[tuple[int, str]] | list[tuple[int, str, str]]):
        options = []
        for msg in user_messages:
            text = msg[1]
            diff_stat = msg[2] if len(msg) > 2 else ""

            clean = " ".join(text.replace("\n", " ").replace("\r", " ").split())
            opt = f"{clean[:50]}..." if len(clean) > 50 else clean
            opt = opt or "(empty message)"
            if diff_stat:
                opt = f"{opt}  [{diff_stat}]"
            options.append(opt)

        items = [msg[0] for msg in user_messages]
        default_val = items[-1] if items else -1
        super().__init__(
            title="### **Select message to rollback to**",
            options=options,
            items=items,
            default_value=default_val
        )

