from rich.markup import escape

from widgets.presentation.screens.base_selection import BaseSelectionScreen


class ResumeScreen(BaseSelectionScreen[str]):
    """Modal session resume screen (/resume)"""

    def __init__(self, sessions: list[dict]):
        options = []
        for s in sessions:
            title = " ".join(str(s.get("title", "")).replace("\n", " ").replace("\r", " ").split())
            escaped_title = escape(title)
            count = s.get("message_count", 0)
            step_str = "step" if count == 1 else "steps"
            options.append(f"{escaped_title} [dim]{escape(f'[{count} {step_str}]')}[/dim]")

        items = [str(s.get("id")) for s in sessions]
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
