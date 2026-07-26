from core.thinking_effort import EFFORT_AUTO, display_thinking_effort
from widgets.screens.base_selection import BaseSelectionScreen


class ThinkingEffortScreen(BaseSelectionScreen[str]):
    def __init__(self, current_effort: str = EFFORT_AUTO):
        current = display_thinking_effort(current_effort)
        options = [
            "auto - use model/provider default",
            "low - fastest, lowest token spend",
            "medium - balanced effort",
            "high - deeper reasoning",
        ]
        items = [EFFORT_AUTO, "low", "medium", "high"]
        super().__init__(
            "### Thinking Effort",
            options,
            items,
            current if current in items else EFFORT_AUTO,
            show_search=False,
        )
