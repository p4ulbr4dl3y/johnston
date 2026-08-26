from core.infrastructure.runtime.thinking_effort import EFFORT_AUTO, display_thinking_effort
from widgets.presentation.screens.base_modal import status_tag
from widgets.presentation.screens.base_selection import BaseSelectionScreen


class ThinkingEffortScreen(BaseSelectionScreen[str]):
    def __init__(self, current_effort: str = EFFORT_AUTO):
        current = display_thinking_effort(current_effort)
        items_with_hints = [
            (EFFORT_AUTO, "Auto", "model default"),
            ("low", "Low", "fast, minimal reasoning"),
            ("medium", "Medium", "balanced"),
            ("high", "High", "deep reasoning"),
        ]
        items = [item for item, _, _ in items_with_hints]
        options = []
        for item, label, hint in items_with_hints:
            prefix = f"{status_tag('ACTIVE')} " if item == current else "  "
            options.append(f"{prefix}{label} [dim #71717a]({hint})[/]")
        super().__init__(
            "### **Select Thinking Effort**",
            options,
            items,
            current,
            show_search=False,
            fit_content=True,
        )
