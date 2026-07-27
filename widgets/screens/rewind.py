from widgets.screens.base_selection import BaseSelectionScreen


class RewindScreen(BaseSelectionScreen[int]):
    """Modal rollback screen (/rewind)"""

    def __init__(self, user_messages: list[tuple[int, str]] | list[tuple[int, str, str]]):
        options = []
        for msg in user_messages:
            text = msg[1]
            diff_stat = msg[2] if len(msg) > 2 else ""

            clean = " ".join(text.replace("\n", " ").replace("\r", " ").split())
            max_text_len = 45
            opt_text = f"{clean[:max_text_len]}..." if len(clean) > max_text_len else clean
            opt_text = opt_text or "(empty message)"
            stat_label = diff_stat or "no checkpoint"
            opt = f"{opt_text}  ({stat_label})"
            options.append(opt)

        items = [msg[0] for msg in user_messages]
        default_val = items[-1] if items else -1
        super().__init__(
            title="### **Select message to rollback to**",
            options=options,
            items=items,
            default_value=default_val
        )

