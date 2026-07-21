from typing import Generic, TypeVar

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Markdown, OptionList

T = TypeVar("T")


class BaseSelectionScreen(ModalScreen[T], Generic[T]):
    """Базовый класс для модальных окон выбора с OptionList"""

    BINDINGS = [("escape", "cancel", "Cancel")]

    def __init__(
        self,
        title: str,
        options: list[str],
        items: list[T],
        default_value: T,
        show_search: bool = False
    ):
        super().__init__()
        self.title = title
        self.raw_options = options
        self.raw_items = items
        self.default_value = default_value
        self.show_search = show_search
        self.filtered_items = list(items)
        self.filtered_options = list(options)

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown(self.title, classes="modal-markdown")
            if self.show_search:
                yield Input(placeholder="Search models...", id="modal-search-input")
            yield OptionList(*self.filtered_options, id="modal-option-list")

    def on_mount(self) -> None:
        opt_list = self.query_one("#modal-option-list", OptionList)
        if self.default_value in self.raw_items:
            try:
                opt_list.highlighted = self.raw_items.index(self.default_value)
            except Exception:
                pass

        if self.show_search:
            self.query_one("#modal-search-input", Input).focus()
        else:
            opt_list.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        query_raw = event.value.strip().lower()
        if not query_raw:
            self.filtered_items = list(self.raw_items)
            self.filtered_options = list(self.raw_options)
        else:
            tokens = query_raw.split()
            scored_matches = []
            for opt, item in zip(self.raw_options, self.raw_items):
                target_str = (str(item) + " " + opt).lower()
                if all(t in target_str for t in tokens):
                    score = 0
                    if query_raw in target_str:
                        score += 100
                    for t in tokens:
                        if target_str.startswith(t) or f"/{t}" in target_str or f"-{t}" in target_str or f":{t}" in target_str:
                            score += 10
                    scored_matches.append((score, opt, item))

            scored_matches.sort(key=lambda x: x[0], reverse=True)
            self.filtered_options = [m[1] for m in scored_matches]
            self.filtered_items = [m[2] for m in scored_matches]

        opt_list = self.query_one("#modal-option-list", OptionList)
        opt_list.clear_options()
        opt_list.add_options(self.filtered_options)
        if self.filtered_options:
            opt_list.highlighted = 0

    def on_input_submitted(self, event: Input.Submitted) -> None:
        opt_list = self.query_one("#modal-option-list", OptionList)
        idx = opt_list.highlighted
        if idx is not None and 0 <= idx < len(self.filtered_items):
            self.dismiss(self.filtered_items[idx])
        else:
            self.dismiss(self.default_value)

    def _on_key(self, event: events.Key) -> None:
        if self.show_search and event.key == "down":
            try:
                search_input = self.query_one("#modal-search-input", Input)
                if search_input.has_focus:
                    opt_list = self.query_one("#modal-option-list", OptionList)
                    opt_list.focus()
                    event.prevent_default()
                    event.stop()
                    return
            except Exception:
                pass
        if self.show_search and event.key == "up":
            try:
                opt_list = self.query_one("#modal-option-list", OptionList)
                if opt_list.has_focus and opt_list.highlighted == 0:
                    search_input = self.query_one("#modal-search-input", Input)
                    search_input.focus()
                    event.prevent_default()
                    event.stop()
                    return
            except Exception:
                pass

    def action_cancel(self) -> None:
        self.dismiss(self.default_value)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.filtered_items):
            self.dismiss(self.filtered_items[event.option_index])
        else:
            self.dismiss(self.default_value)
