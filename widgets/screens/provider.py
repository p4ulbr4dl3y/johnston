from widgets.screens.base_selection import BaseSelectionScreen

class ProviderScreen(BaseSelectionScreen[str]):
    """Modal provider selection screen (/provider)"""

    def __init__(self, providers: dict):
        providers_list = list(providers.values())
        options = [
            f"{p['name']}" + (f" — {p['description']}" if p.get('description') else "")
            for p in providers_list
        ]
        items = [p["key"] for p in providers_list]
        super().__init__(
            title="### **Select AI provider (/provider)**",
            options=options,
            items=items,
            default_value=""
        )
