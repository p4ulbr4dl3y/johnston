from widgets.screens.base_selection import BaseSelectionScreen


class ProviderScreen(BaseSelectionScreen[str]):
    """Modal provider selection screen (/provider)"""

    def __init__(self, providers: dict):
        providers_list = list(providers.values())
        options = [p["name"] for p in providers_list]
        items = [p["key"] for p in providers_list]
        super().__init__(
            title="### **Select AI provider**",
            options=options,
            items=items,
            default_value="",
            show_search=True,
            search_placeholder="Search providers..."
        )
