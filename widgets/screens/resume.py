from widgets.screens.base_selection import BaseSelectionScreen


class ResumeScreen(BaseSelectionScreen[str]):
    """Modal session resume screen (/resume)"""

    def __init__(self, sessions: list[dict]):
        options = []
        for s in sessions:
            title = " ".join(str(s.get('title', '')).replace("\n", " ").replace("\r", " ").split())
            options.append(f"{title} ({s.get('message_count', 0)} msgs)")

        items = [s["id"] for s in sessions]
        super().__init__(
            title="### **Select session to resume**",
            options=options,
            items=items,
            default_value=""
        )

