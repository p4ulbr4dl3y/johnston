from core.infrastructure.runtime.thinking_effort import EFFORT_AUTO, display_thinking_effort
from widgets.presentation.screens.base_modal import status_tag
from widgets.presentation.screens.base_selection import BaseSelectionScreen


class ThinkingEffortScreen(BaseSelectionScreen[str]):
    def __init__(self, current_effort: str = EFFORT_AUTO):
        current = display_thinking_effort(current_effort)
        items = [EFFORT_AUTO, "low", "medium", "high"]
        descriptions = {
            EFFORT_AUTO: "use model/provider default",
            "low": "fastest, lowest token spend",
            "medium": "balanced effort",
            "high": "deeper reasoning",
        }
        options = []
        for item in items:
            prefix = f"{status_tag('ACTIVE')} " if item == current else ""
            options.append(f"{prefix}{item} - {descriptions[item]}")
        super().__init__(
            "### **Select Thinking Effort**",
            options,
            items,
            current,
            show_search=False,
        )
