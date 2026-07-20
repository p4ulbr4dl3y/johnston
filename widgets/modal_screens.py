from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Vertical, Horizontal
from textual.widgets import Label, Button, OptionList
from textual import events

class HelpScreen(ModalScreen[None]):
    """Модальное окно справки (/help)"""
    
    BINDINGS = [("escape", "close", "Закрыть")]

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Label("💡 **Справка по командам**", classes="modal-title")
            yield Label(
                "• `/help` — Открыть эту справку\n"
                "• `/resume` — Откат истории чата к выбранному сообщению\n\n"
                "**Горячие клавиши:**\n"
                "• `Enter` — Отправить сообщение\n"
                "• `Ctrl+Enter` / `Shift+Enter` — Перенос строки\n"
                "• `↑ / ↓` — Навигация по истории запросов (зацикленная)\n"
                "• `Ctrl+C` / `Esc` — Выход из приложения",
                classes="modal-body"
            )
            with Horizontal(classes="modal-buttons"):
                yield Button("Понятно", id="btn-close", variant="primary")

    def action_close(self) -> None:
        self.dismiss(None)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-close":
            self.dismiss(None)


class ResumeScreen(ModalScreen[int]):
    """Модальное окно отката истории (/resume)"""

    BINDINGS = [("escape", "cancel", "Отмена")]

    def __init__(self, user_messages: list[tuple[int, str]]):
        super().__init__()
        self.user_messages = user_messages

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Label("↺ **Выберите сообщение для отката**", classes="modal-title")
            
            options = [
                f"{i+1}. {text[:45]}..." if len(text) > 45 else f"{i+1}. {text}"
                for i, (_, text) in enumerate(self.user_messages)
            ]
            yield OptionList(*options, id="resume-option-list")
            
            with Horizontal(classes="modal-buttons"):
                yield Button("Откатить", id="btn-confirm", variant="primary")
                yield Button("Отмена", id="btn-cancel")

    def action_cancel(self) -> None:
        self.dismiss(-1)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "btn-cancel":
            self.dismiss(-1)
        elif event.button.id == "btn-confirm":
            option_list = self.query_one("#resume-option-list", OptionList)
            if option_list.highlighted is not None:
                selected_idx = self.user_messages[option_list.highlighted][0]
                self.dismiss(selected_idx)
            else:
                self.dismiss(-1)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        selected_idx = self.user_messages[event.option_index][0]
        self.dismiss(selected_idx)
