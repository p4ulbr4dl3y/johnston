from textual.app import ComposeResult
from textual.containers import Vertical, Container
from textual.widgets import Label, Button, OptionList, Select, Static
from mock_agent import PERSONAS

class Sidebar(Vertical):
    """Боковая панель с навигацией и настройками"""

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

        yield Label("Персона агента:", classes="section-label")
        persona_options = [(info["name"], key) for key, info in PERSONAS.items()]
        yield Select(
            options=persona_options,
            value="assistant",
            id="persona-select",
            allow_blank=False
        )

        yield Container(
            Label("ℹ️ **Инфо**", classes="info-title"),
            Static("Textual v8.2\nEngine: Mock Streaming", id="info-text"),
            id="sidebar-info"
        )
