from rich.markup import escape

from widgets.presentation.screens.base_modal import status_tag
from widgets.presentation.screens.base_selection import BaseSelectionScreen


class ResumeScreen(BaseSelectionScreen[str]):
    """Modal session resume screen (/resume)"""

    def __init__(self, sessions: list[dict], current_session_id: str | None = None):
        options = []
        items = []
        for s in sessions:
            sid = str(s.get("id"))
            items.append(sid)
            title = " ".join(str(s.get("title", "")).replace("\n", " ").replace("\r", " ").split())
            if len(title) > 55:
                title = title[:55] + "..."
            escaped_title = escape(title)
            count = s.get("message_count", 0)
            step_str = "step" if count == 1 else "steps"
            prefix = f" {status_tag('ACTIVE')} " if (current_session_id and sid == str(current_session_id)) else "   "
            options.append(f"{prefix}{escaped_title} [dim]{escape(f'({count} {step_str})')}[/dim]")

        if current_session_id and str(current_session_id) in items:
            default_val = str(current_session_id)
        else:
            default_val = items[0] if items else ""

        super().__init__(
            title="### **Select Session to Resume**",
            options=options,
            items=items,
            default_value=default_val,
            show_search=True,
            search_placeholder="Search...",
            dialog_classes="modal-dialog-medium",
        )
