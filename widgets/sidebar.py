from textual.app import ComposeResult
from textual.containers import Vertical, Container
from textual.widgets import Label, Button, OptionList, Select, Static
from provider_manager import ProviderManager
from session_manager import SessionManager

class Sidebar(Vertical):
    """Боковая панель с навигацией, выбором провайдеров и сессий из ~/.tui"""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pm = ProviderManager()
        self.sm = SessionManager()
        self.session_ids = []

    def compose(self) -> ComposeResult:
        yield Label("💬 **Textual AI Chat**", id="sidebar-title")
        
        yield Container(
            Button("➕ Новый диалог", id="btn-new-chat", variant="primary"),
            id="new-chat-container"
        )

        yield Label("Диалоги:", classes="section-label")
        yield OptionList(id="session-list")

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

    def on_mount(self) -> None:
        self.refresh_sessions()

    def refresh_sessions(self) -> None:
        """Обновляет список сессий в боковом меню"""
        session_list = self.query_one("#session-list", OptionList)
        session_list.clear_options()
        
        sessions = self.sm.list_sessions()
        active_sid = self.sm.get_active_session_id()
        self.session_ids = []

        active_idx = 0
        for idx, s in enumerate(sessions):
            self.session_ids.append(s["id"])
            prefix = "▶ " if s["id"] == active_sid else "  "
            title = f"{prefix}{s['title'][:20]}"
            session_list.add_option(title)
            if s["id"] == active_sid:
                active_idx = idx

        if self.session_ids:
            session_list.highlighted = active_idx
