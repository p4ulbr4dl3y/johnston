from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Vertical
from textual.widgets import OptionList, Markdown

class HelpScreen(ModalScreen[None]):
    """Модальное окно справки (/help)"""
    
    BINDINGS = [
        ("escape", "close", "Закрыть"),
        ("enter", "close", "Закрыть"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown(
                "### 💡 **Справка по командам**\n\n"
                "* `/help` — Открыть эту справку\n"
                "* `/new` — Создать новый диалог (сессию)\n"
                "* `/rewind` — Откат истории чата к выбранному сообщению\n"
                "* `/resume` — Переключение и возобновление диалогов из сессий\n\n"
                "**Горячие клавиши:**\n"
                "* `Enter` — Отправить сообщение\n"
                "* `Ctrl+Enter` / `Shift+Enter` — Перенос строки\n"
                "* `↑ / ↓` — Навигация по истории запросов (зацикленная)\n"
                "* `Ctrl+C` / `Ctrl+Q` — Выход из приложения",
                classes="modal-markdown"
            )

    def action_close(self) -> None:
        self.dismiss(None)


class RewindScreen(ModalScreen[int]):
    """Модальное окно отката истории (/rewind)"""

    BINDINGS = [("escape", "cancel", "Отмена")]

    def __init__(self, user_messages: list[tuple[int, str]]):
        super().__init__()
        self.user_messages = user_messages

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("### ↺ **Выберите сообщение для отката**", classes="modal-markdown")
            
            options = [
                f"{i+1}. {text[:50]}..." if len(text) > 50 else f"{i+1}. {text}"
                for i, (_, text) in enumerate(self.user_messages)
            ]
            yield OptionList(*options, id="rewind-option-list")

    def action_cancel(self) -> None:
        self.dismiss(-1)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Выбор элемента по Enter или клику"""
        selected_idx = self.user_messages[event.option_index][0]
        self.dismiss(selected_idx)


class ResumeScreen(ModalScreen[str]):
    """Модальное окно возобновления/выбора сессии (/resume)"""

    BINDINGS = [("escape", "cancel", "Отмена")]

    def __init__(self, sessions: list[dict]):
        super().__init__()
        self.sessions = sessions

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown("### 📁 **Выберите сессию для возобновления (/resume)**", classes="modal-markdown")
            
            options = [
                f"💬 {s['title']} ({s['message_count']} сообщ.)"
                for s in self.sessions
            ]
            yield OptionList(*options, id="resume-session-option-list")

    def action_cancel(self) -> None:
        self.dismiss("")

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.sessions):
            selected_session_id = self.sessions[event.option_index]["id"]
            self.dismiss(selected_session_id)
        else:
            self.dismiss("")
