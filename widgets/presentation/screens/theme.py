"""Theme selection screen for choosing color palettes."""

from typing import Optional

from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from core.theme_manager import theme_manager
from widgets.presentation.screens.base_modal import BaseModalScreen, status_tag
from widgets.presentation.screens.base_selection import HeaderWrapOptionList, ModalSearchNavMixin
from widgets.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT_ID,
    MODAL_MARKDOWN,
    MODAL_MARKDOWN_CENTERED,
    MODAL_SEARCH_INPUT_ID,
)
from widgets.utils.key_aliases import expand_bindings


class ThemeScreen(ModalSearchNavMixin, BaseModalScreen[Optional[str]]):
    """Modal screen for selecting UI and syntax color theme."""

    search_nav_option_list_id = "theme-option-list"
    search_nav_filtered_attr = "filtered_themes"

    BINDINGS = expand_bindings([
        ("escape", "cancel", "Cancel"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ])

    def __init__(self) -> None:
        super().__init__()
        self.themes = theme_manager.list_themes()
        self.options: list[str] = []
        self.filtered_themes = list(self.themes)
        self.filtered_options: list[str] = []
        self.search_query = ""
        self.load_options()

    def load_options(self) -> None:
        current_name = theme_manager.current_theme.name
        self.options = []
        for t in self.themes:
            is_active = t.name == current_name
            tag = status_tag("ACTIVE" if is_active else "THEME")
            mode = "Dark" if t.dark else "Light"
            self.options.append(f"{tag} {t.label} ({mode})")
        self.filtered_themes = list(self.themes)
        self.filtered_options = list(self.options)

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID):
            from textual.widgets import Markdown
            yield Markdown("### Select Theme", classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}")
            yield Input(
                placeholder="Search themes...",
                id=MODAL_SEARCH_INPUT_ID,
            )
            yield HeaderWrapOptionList(
                *[Option(opt, id=f"theme_{t.name}") for opt, t in zip(self.filtered_options, self.filtered_themes)],
                id="theme-option-list",
            )
            yield Markdown("Enter select • Esc cancel", id=MODAL_HINT_ID)

    def on_mount(self) -> None:
        super().on_mount()
        search_input = self.query_one(f"#{MODAL_SEARCH_INPUT_ID}", Input)
        search_input.focus()
        try:
            opt_list = self.query_one("#theme-option-list", HeaderWrapOptionList)
            current_name = theme_manager.current_theme.name
            for i, t in enumerate(self.filtered_themes):
                if t.name == current_name:
                    opt_list.highlighted = i
                    break
            else:
                if self.filtered_themes:
                    opt_list.highlighted = 0
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == MODAL_SEARCH_INPUT_ID:
            query = event.value.strip().lower()
            self.search_query = query
            self.filter_options()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == MODAL_SEARCH_INPUT_ID:
            try:
                opt_list = self.query_one("#theme-option-list", HeaderWrapOptionList)
                idx = opt_list.highlighted
                if idx is not None and 0 <= idx < len(self.filtered_themes):
                    selected_theme = self.filtered_themes[idx]
                    self.dismiss(selected_theme.name)
                    return
            except Exception:
                pass
            self.dismiss(None)

    def _on_key(self, event: events.Key) -> None:
        self._handle_search_navigation(event)

    def filter_options(self) -> None:
        current_name = theme_manager.current_theme.name
        filtered = []
        filtered_opts = []
        for t in self.themes:
            if self.search_query in t.name.lower() or self.search_query in t.label.lower():
                filtered.append(t)
                is_active = t.name == current_name
                tag = status_tag("ACTIVE" if is_active else "THEME")
                mode = "Dark" if t.dark else "Light"
                filtered_opts.append(f"{tag} {t.label} ({mode})")
        self.filtered_themes = filtered
        self.filtered_options = filtered_opts

        option_list = self.query_one("#theme-option-list", HeaderWrapOptionList)
        option_list.clear_options()
        for opt, t in zip(self.filtered_options, self.filtered_themes):
            option_list.add_option(Option(opt, id=f"theme_{t.name}"))
        if self.filtered_themes:
            option_list.highlighted = 0

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_id and event.option_id.startswith("theme_"):
            theme_name = event.option_id[len("theme_"):]
            self.dismiss(theme_name)

    def action_cancel(self) -> None:
        self.dismiss(None)
