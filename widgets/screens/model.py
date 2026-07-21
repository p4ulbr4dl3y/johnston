from widgets.screens.base_selection import BaseSelectionScreen


class ModelScreen(BaseSelectionScreen[str]):
    """Modal model selection screen (/models)"""

    def __init__(self, models: list[str], current_model: str = ""):
        options = [
            f"{'▶ ' if m == current_model else '  '}{m}"
            for m in models
        ]
        super().__init__(
            title="### **Select provider model (/models)**",
            options=options,
            items=models,
            default_value=""
        )
