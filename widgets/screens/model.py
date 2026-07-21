from widgets.screens.base_selection import BaseSelectionScreen


class ModelScreen(BaseSelectionScreen[str]):
    """Modal model selection screen (/models)"""

    def __init__(self, models: list[str], current_model: str = ""):
        super().__init__(
            title="### **Select provider model (/models)**",
            options=models,
            items=models,
            default_value=current_model if current_model in models else (models[0] if models else ""),
            show_search=True
        )
