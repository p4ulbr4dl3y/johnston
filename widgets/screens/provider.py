from widgets.screens.base_selection import BaseSelectionScreen


class ProviderScreen(BaseSelectionScreen[str]):
    """Modal provider selection screen (/provider)"""

    def __init__(self, providers: dict, active_key: str = ""):
        providers_list = list(providers.values())
        options = [p["name"] for p in providers_list]
        items = [p["key"] for p in providers_list]
        super().__init__(
            title="### **Select AI provider**",
            options=options,
            items=items,
            default_value=active_key if active_key in items else (items[0] if items else ""),
            show_search=True,
            search_placeholder="Search providers..."
        )
