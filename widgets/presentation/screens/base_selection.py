import re
from typing import Generic, TypeVar

from textual import events
from textual._widget_navigation import find_first_enabled, find_last_enabled
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Markdown, OptionList
from textual.widgets.option_list import Option

from widgets.presentation.screens.base_modal import BaseModalScreen
from widgets.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT_ID,
    MODAL_MARKDOWN,
    MODAL_MARKDOWN_CENTERED,
    MODAL_OPTION_LIST_ID,
    MODAL_SEARCH_INPUT,
    MODAL_SEARCH_INPUT_ID,
    TAB_KEYS,
)

T = TypeVar("T")

_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


class HeaderWrapOptionList(OptionList):
    """OptionList that keeps the first group's header in view on wrap-around.

    When the highlight wraps from the last enabled option to the first, the
    list is scrolled so the very first row (a disabled section header such as
    "Global") stays visible above the highlighted first skill.
    """

    def _on_mouse_move(self, event: events.MouseMove) -> None:
        super()._on_mouse_move(event)
        option_index = event.style.meta.get("option")
        if option_index is not None and 0 <= option_index < len(self.options):
            if not self.options[option_index].disabled and self.highlighted != option_index:
                self.highlighted = option_index

    def action_cursor_down(self) -> None:
        last = find_last_enabled(self.options)
        if self.highlighted is not None and last is not None and self.highlighted == last:
            super().action_cursor_down()
            self.scroll_home(animate=False)
            return
        super().action_cursor_down()

    def action_cursor_up(self) -> None:
        first = find_first_enabled(self.options)
        if self.highlighted is not None and first is not None and self.highlighted == first:
            super().action_cursor_up()
            self.scroll_end(animate=False)
            return
        super().action_cursor_up()


class ModalSearchNavMixin:
    """Shared up/down navigation from the search Input to the OptionList.

    Used by the MCP / permissions / skills modals which are not
    ``BaseSelectionScreen`` subclasses but share the same key handling.
    """

    # Subclasses must set these:
    search_nav_option_list_id: str = ""
    search_nav_filtered_attr: str = ""

    def _handle_search_navigation(self, event: events.Key) -> bool:
        """Handle up/down keys while the search Input has focus.

        Returns True if the event was consumed, False otherwise.
        """
        if event.key not in ("down", "up"):
            return False
        try:
            search_input = self.query_one(MODAL_SEARCH_INPUT, Input)
            if search_input.has_focus:
                opt_list = self.query_one(f"#{self.search_nav_option_list_id}", OptionList)
                filtered = getattr(self, self.search_nav_filtered_attr, [])
                if opt_list.highlighted is None and filtered:
                    opt_list.highlighted = 0
                elif opt_list.highlighted is not None:
                    if event.key == "down":
                        opt_list.action_cursor_down()
                    else:
                        opt_list.action_cursor_up()
                event.prevent_default()
                event.stop()
                return True
        except Exception:
            pass
        return False


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
        hint_text: str = "enter: select • ↑↓: nav • esc: cancel",
        option_list_id: str = MODAL_OPTION_LIST_ID,
        dialog_classes: str = "",
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
        self.dialog_classes = dialog_classes
        self.filtered_items = list(items)
        self.filtered_options = list(options)
        self._norm_targets: dict[int, str] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID, classes=self.dialog_classes or None):
            yield Markdown(self.title, classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}")
            if self.show_search:
                yield Input(placeholder=self.search_placeholder, id=MODAL_SEARCH_INPUT_ID)
            yield HeaderWrapOptionList(*self.filtered_options, id=self.option_list_id)
            yield Label(self.hint_text, id=MODAL_HINT_ID)

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
            self.query_one(MODAL_SEARCH_INPUT, Input).focus()
        else:
            opt_list.focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        query_raw = event.value.strip().lower()
        if not query_raw:
            self.filtered_items = list(self.raw_items)
            self.filtered_options = list(self.raw_options)
        else:
            tokens = query_raw.split()
            filtered_options = []
            filtered_items = []

            current_header_opt = None
            current_header_item = None
            current_section_matches = []
            first_matched_group = True

            for idx, (opt, item) in enumerate(zip(self.raw_options, self.raw_items)):
                if item is None:
                    opt_str = str(opt.prompt if hasattr(opt, "prompt") else opt).strip()
                    if not opt_str:
                        continue
                    if current_section_matches:
                        if current_header_opt is not None:
                            if not first_matched_group:
                                filtered_options.append(Option("", disabled=True))
                                filtered_items.append(None)
                            first_matched_group = False
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
                    norm_target = self._norm_targets.get(idx)
                    if norm_target is None:
                        norm_target = _NORMALIZE_RE.sub(" ", raw_target)
                        if len(self._norm_targets) >= 512:
                            self._norm_targets.clear()
                        self._norm_targets[idx] = norm_target
                    target_str = f"{raw_target} {norm_target}"

                    if all(t in target_str for t in tokens):
                        current_section_matches.append((opt, item))

            if current_section_matches:
                if current_header_opt is not None:
                    if not first_matched_group:
                        filtered_options.append(Option("", disabled=True))
                        filtered_items.append(None)
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
        if self.show_search and event.key in TAB_KEYS:
            event.prevent_default()
            event.stop()
            return

        if self.show_search and event.key in ("down", "up"):
            try:
                search_input = self.query_one(MODAL_SEARCH_INPUT, Input)
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
