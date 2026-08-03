from widgets.screens.base_selection import BaseSelectionScreen


class ResumeScreen(BaseSelectionScreen[str]):
    """Modal session resume screen (/resume)"""

    def __init__(self, sessions: list[dict]):
        options = []
        for s in sessions:
            title = " ".join(str(s.get('title', '')).replace("\n", " ").replace("\r", " ").split())
            max_title_len = 30
            title_text = f"{title[:max_title_len]}..." if len(title) > max_title_len else title
            count = s.get('message_count', 0)
            step_str = "step" if count == 1 else "steps"
            options.append(f"{title_text} \\[{count} {step_str}]")


        items = [s["id"] for s in sessions]
        default_val = items[0] if items else ""
        super().__init__(
            title="### **Select Session to Resume**",
            options=options,
            items=items,
            default_value=default_val
        )

