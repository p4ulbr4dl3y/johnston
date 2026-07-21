from typing import Generic, TypeVar

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Markdown, OptionList

T = TypeVar("T")

class BaseSelectionScreen(ModalScreen[T], Generic[T]):
    """Базовый класс для модальных окон выбора с OptionList"""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(self, title: str, options: list[str], items: list[T], default_value: T):
        super().__init__()
        self.title = title
        self.options = options
        self.items = items
        self.default_value = default_value

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown(self.title, classes="modal-markdown")
            yield OptionList(*self.options)

    def on_mount(self) -> None:
        opt_list = self.query_one(OptionList)
        opt_list.focus()
        if self.default_value in self.items:
            try:
                opt_list.highlighted = self.items.index(self.default_value)
            except Exception:
                pass

    def action_cancel(self) -> None:
        self.dismiss(self.default_value)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.items):
            self.dismiss(self.items[event.option_index])
        else:
            self.dismiss(self.default_value)
