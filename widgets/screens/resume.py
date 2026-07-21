from widgets.screens.base_selection import BaseSelectionScreen


class ResumeScreen(BaseSelectionScreen[str]):
    """Modal session resume screen (/resume)"""

    def __init__(self, sessions: list[dict]):
        options = [
            f"{s['title']} ({s['message_count']} msgs)"
            for s in sessions
        ]
        items = [s["id"] for s in sessions]
        super().__init__(
            title="### **Select session to resume**",
            options=options,
            items=items,
            default_value=""
        )
