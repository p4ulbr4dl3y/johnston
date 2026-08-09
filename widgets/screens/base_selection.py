from typing import Generic, TypeVar

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Markdown, OptionList

from widgets.screens.base_modal import BaseModalScreen

T = TypeVar("T")


class BaseSelectionScreen(BaseModalScreen[T], Generic[T]):
    """Base class for selection modal screens with OptionList"""

    def __init__(
        self,
        title: str,
        options: list[str],
        items: list[T],
        default_value: T,
        show_search: bool = False,
        search_placeholder: str = "Search...",
        hint_text: str = "enter: select • ↑/↓: navigate • esc: cancel",
        option_list_id: str = "modal-option-list",
    ):
        super().__init__()
        self.title = title
        self.raw_options = options
        self.raw_items = items
        self.default_value = default_value
        self.show_search = show_search
        self.search_placeholder = search_placeholder
        self.hint_text = hint_text
        self.option_list_id = option_list_id
        self.filtered_items = list(items)
        self.filtered_options = list(options)

    def compose(self) -> ComposeResult:
        with Vertical(id="modal-dialog"):
            yield Markdown(self.title, classes="modal-markdown modal-markdown-centered")
            if self.show_search:
                yield Input(placeholder=self.search_placeholder, id="modal-search-input")
            yield OptionList(*self.filtered_options, id=self.option_list_id)
            yield Label(self.hint_text, id="modal-hint")

    def on_mount(self) -> None:
        opt_list = self.query_one(f"#{self.option_list_id}", OptionList)
        default_idx = None
        if self.default_value is not None and self.default_value in self.raw_items:
            try:
                default_idx = self.raw_items.index(self.default_value)
            except Exception:
                pass

        opt_list.highlighted = default_idx
        if default_idx is not None:
            try:
                opt_list.scroll_to_highlight()
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
            import re
            tokens = query_raw.split()
            filtered_options = []
            filtered_items = []

            current_header_opt = None
            current_header_item = None
            current_section_matches = []

            for opt, item in zip(self.raw_options, self.raw_items):
                if item is None:
                    opt_str = str(opt.prompt if hasattr(opt, "prompt") else opt).strip()
                    if not opt_str:
                        continue
                    if current_section_matches:
                        if current_header_opt is not None:
                            filtered_options.append(current_header_opt)
                            filtered_items.append(current_header_item)
                        for m_opt, m_item in current_section_matches:
                            filtered_options.append(m_opt)
                            filtered_items.append(m_item)
                        current_section_matches = []
                    current_header_opt = opt
                    current_header_item = item
                else:
                    opt_text = opt.prompt if hasattr(opt, "prompt") else str(opt)
                    raw_target = f"{item} {opt_text}".lower()
                    norm_target = re.sub(r"[^a-z0-9]+", " ", raw_target)
                    target_str = f"{raw_target} {norm_target}"

                    if all(t in target_str for t in tokens):
                        current_section_matches.append((opt, item))

            if current_section_matches:
                if current_header_opt is not None:
                    filtered_options.append(current_header_opt)
                    filtered_items.append(current_header_item)
                for m_opt, m_item in current_section_matches:
                    filtered_options.append(m_opt)
                    filtered_items.append(m_item)

            self.filtered_options = filtered_options
            self.filtered_items = filtered_items

        opt_list = self.query_one(f"#{self.option_list_id}", OptionList)
        opt_list.clear_options()
        opt_list.add_options(self.filtered_options)
        default_idx = None
        if self.default_value is not None and self.default_value in self.filtered_items:
            try:
                default_idx = self.filtered_items.index(self.default_value)
            except Exception:
                pass
        opt_list.highlighted = default_idx

    def on_input_submitted(self, event: Input.Submitted) -> None:
        opt_list = self.query_one(f"#{self.option_list_id}", OptionList)
        idx = opt_list.highlighted
        if idx is not None and 0 <= idx < len(self.filtered_items):
            item = self.filtered_items[idx]
            if item is not None:
                self.dismiss(item)
                return

        for item in self.filtered_items:
            if item is not None:
                self.dismiss(item)
                return

        self.dismiss(self.default_value)

    def _on_key(self, event: events.Key) -> None:
        if self.show_search and event.key in ("shift+tab", "backtab", "shift_tab"):
            event.prevent_default()
            event.stop()
            return

        if self.show_search and event.key in ("down", "up"):
            try:
                search_input = self.query_one("#modal-search-input", Input)
                if search_input.has_focus:
                    opt_list = self.query_one(f"#{self.option_list_id}", OptionList)
                    if opt_list.highlighted is None:
                        for i, it in enumerate(self.filtered_items):
                            if it is not None:
                                opt_list.highlighted = i
                                break
                    else:
                        if event.key == "down":
                            opt_list.action_cursor_down()
                        else:
                            opt_list.action_cursor_up()
                    event.prevent_default()
                    event.stop()
                    return
            except Exception:
                pass

    def action_cancel(self) -> None:
        self.dismiss(None)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if 0 <= event.option_index < len(self.filtered_items):
            item = self.filtered_items[event.option_index]
            if item is not None:
                self.dismiss(item)
                return
            event.stop()
            return
