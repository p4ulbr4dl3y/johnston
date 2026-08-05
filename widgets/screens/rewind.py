from rich.markup import escape

from widgets.screens.base_selection import BaseSelectionScreen


class RewindScreen(BaseSelectionScreen[int]):
    """Modal rollback screen (/rewind)"""

    def __init__(
        self,
        user_messages: list[tuple[int, str]] | list[tuple[int, str, str]],
        checkpoints_enabled: bool = True,
    ):
        options = []
        for msg in user_messages:
            text = msg[1]
            diff_stat = msg[2] if len(msg) > 2 else ""

            clean = " ".join(text.replace("\n", " ").replace("\r", " ").split())
            max_text_len = 28
            opt_text = f"{clean[:max_text_len]}..." if len(clean) > max_text_len else clean
            opt_text = opt_text or "(empty message)"
            escaped_text = escape(opt_text)

            if checkpoints_enabled:
                stat_label = diff_stat or "no checkpoint"
                opt = f"{escaped_text} [dim]{escape(f'[{stat_label}]')}[/dim]"
            else:
                opt = escaped_text
            options.append(opt)

        title = "### **Select Message to Rollback To**"

        items = [msg[0] for msg in user_messages]
        default_val = items[-1] if items else -1
        super().__init__(
            title=title,
            options=options,
            items=items,
            default_value=default_val
        )

