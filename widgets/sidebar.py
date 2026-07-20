from textual.app import ComposeResult
from textual.containers import Vertical, Container
from textual.widgets import Label, Button, OptionList, Select, Static
from provider_manager import ProviderManager

class Sidebar(Vertical):
    """Боковая панель с навигацией и выбором провайдеров из ~/.tui"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pm = ProviderManager()

    def compose(self) -> ComposeResult:
        yield Label("💬 **Textual AI Chat**", id="sidebar-title")
        
        yield Container(
            Button("➕ Новый диалог", id="btn-new-chat", variant="primary"),
            id="new-chat-container"
        )

        yield Label("Диалоги:", classes="section-label")
        yield OptionList(
            "Чат #1 (Главный)",
            id="session-list"
        )

        yield Label("Провайдер агента (~/.tui):", classes="section-label")
        providers = self.pm.load_providers()
        provider_options = [(info["name"], key) for key, info in providers.items()]
        active_key = self.pm.get_active_provider_key()
        
        if not provider_options:
            provider_options = [("Нет провайдеров", "none")]
            active_key = "none"

        yield Select(
            options=provider_options,
            value=active_key if active_key in providers else provider_options[0][1],
            id="persona-select",
            allow_blank=False
        )

        yield Container(
            Label("ℹ️ **Инфо**", classes="info-title"),
            Static("Textual v8.2\nConfig: ~/.tui", id="info-text"),
            id="sidebar-info"
        )
