from rich.markup import escape

from core.application.session.actions import RewindEntry
from widgets.presentation.screens.base_selection import BaseSelectionScreen


class RewindScreen(BaseSelectionScreen[int]):
    """Modal rollback screen (/rewind)"""

    def __init__(
        self,
        user_messages: list[RewindEntry],
        checkpoints_enabled: bool = True,
    ):
        options = []
        for msg in user_messages:
            text = msg.text
            diff_stat = msg.git_stats

            clean = " ".join(text.replace("\n", " ").replace("\r", " ").split())
            if len(clean) > 55:
                clean = clean[:55] + "..."
            opt_text = clean or "(empty message)"
            escaped_text = escape(opt_text)

            if checkpoints_enabled:
                stat_label = diff_stat or "no checkpoint"
                opt = f"{escaped_text} [dim]{escape(f'[{stat_label}]')}[/dim]"
            else:
                opt = escaped_text
            options.append(opt)

        title = "### **Select Message to Rollback To**"

        items = [m.index for m in user_messages]
        default_val = items[-1] if items else -1
        super().__init__(
            title=title,
            options=options,
            items=items,
            default_value=default_val,
            dialog_classes="modal-dialog-medium",
        )
