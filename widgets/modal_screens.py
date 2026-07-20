from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Vertical
from textual.widgets import OptionList, Markdown

class HelpScreen(ModalScreen[None]):
    """Модальное окно справки (/help) с рендерингом Markdown"""
    
    BINDINGS = [
        ("escape", "close", "Закрыть"),
        ("enter", "close", "Закрыть"),
    ]

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown(
                "### 💡 **Справка по командам**\n\n"
                "* `/help` — Открыть эту справку\n"
                "* `/resume` — Откат истории чата к выбранному сообщению\n\n"
                "**Горячие клавиши:**\n"
                "* `Enter` — Отправить сообщение\n"
                "* `Ctrl+Enter` / `Shift+Enter` — Перенос строки\n"
                "* `↑ / ↓` — Навигация по истории запросов (зацикленная)\n"
                "* `Ctrl+C` / `Esc` — Выход из приложения",
                classes="modal-markdown"
            )

    def action_close(self) -> None:
        self.dismiss(None)


class ResumeScreen(ModalScreen[int]):
    """Модальное окно отката истории (/resume) с рендерингом Markdown и выбором по Enter"""

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
            yield OptionList(*options, id="resume-option-list")

    def action_cancel(self) -> None:
        self.dismiss(-1)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        """Выбор элемента по Enter или клику"""
        selected_idx = self.user_messages[event.option_index][0]
        self.dismiss(selected_idx)
