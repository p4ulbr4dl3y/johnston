from dataclasses import dataclass
from typing import Optional

from rich.markup import escape
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, OptionList
from textual.widgets.option_list import Option

from core.application.session.actions import RewindEntry
from widgets.presentation.screens.base_modal import BaseModalScreen
from widgets.presentation.screens.base_selection import HeaderWrapOptionList, ModalSearchNavMixin
from widgets.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT,
    MODAL_HINT_ID,
    MODAL_OPTION_LIST,
    MODAL_OPTION_LIST_ID,
    MODAL_SEARCH_INPUT,
    MODAL_SEARCH_INPUT_ID,
    TAB_KEYS,
)
from widgets.presentation.widgets.modal_header import ModalHeader
from widgets.presentation.widgets.modal_hint import ModalHint
from widgets.utils.row_format import MODAL_WIDE_ROW_WIDTH, ellipsize, format_badge_row, option_list_row_width

REWIND_CURRENT_STATE = -1


@dataclass
class RewindSelection:
    index: int
    restore_code: bool = True


def format_rewind_files(
    changed_files: list[str], git_stats: str = "", max_show: int = 4, max_width: int = 0
) -> Text:
    """Format rewind file list with rich styling without bullet/indent noise."""
    t = Text()
    if not changed_files:
        return t
    stat_label = f" ({git_stats})" if git_stats else ""
    t.append("Files to revert", style="bold")
    if stat_label:
        t.append(stat_label, style="dim")
    t.append(":\n", style="bold")

    lines: list[tuple[str, str]] = []
    for f in changed_files[:max_show]:
        display_f = ellipsize(f, max(15, max_width - 4)) if max_width > 0 else f
        lines.append((f"  {display_f}", ""))

    if len(changed_files) > max_show:
        rem = len(changed_files) - max_show
        lines.append((f"  ... and {rem} more", "italic dim"))

    for i, (line_text, line_style) in enumerate(lines):
        t.append(line_text, style=line_style)
        if i < len(lines) - 1:
            t.append("\n")

    return t


class RewindScreen(ModalSearchNavMixin, BaseModalScreen[Optional[RewindSelection]]):
    """Modal rollback screen (/rewind) with separate action selection modal."""

    search_nav_option_list_id: str = MODAL_OPTION_LIST_ID
    search_nav_filtered_attr: str = "filtered_options"

    def __init__(
        self,
        user_messages: list[RewindEntry],
        checkpoints_enabled: bool = True,
        session_id: Optional[str] = None,
        project_path: Optional[str] = None,
    ):
        super().__init__()
        self.user_messages = user_messages
        self.checkpoints_enabled = checkpoints_enabled
        self.session_id = session_id
        self.project_path = project_path
        self.search_query = ""
        self.filtered_entries: list[RewindEntry] = list(user_messages)

        options = self._format_step1_options(MODAL_WIDE_ROW_WIDTH, self.filtered_entries)

        self.title = "Select Message to Rollback To"
        self.hint_text = "enter: select • esc: cancel"
        self.raw_options = list(options)
        self.raw_items = [m.index for m in user_messages]
        self.raw_items.append(REWIND_CURRENT_STATE)
        self.filtered_options = list(options)
        self.filtered_items = list(self.raw_items)
        self.default_value = REWIND_CURRENT_STATE
        self.option_list_id = MODAL_OPTION_LIST_ID

    def _row_width(self) -> int:
        try:
            opt_list = self.query_one(MODAL_OPTION_LIST, OptionList)
        except Exception:
            opt_list = None
        return option_list_row_width(opt_list, MODAL_WIDE_ROW_WIDTH)

    def _format_step1_options(self, target_width: int, entries: list[RewindEntry]) -> list[str]:
        options = []
        for m in entries:
            clean = " ".join(m.text.replace("\n", " ").replace("\r", " ").split())
            if not clean:
                clean = "(empty message)"
            badge_plain = (m.git_stats or "no checkpoint") if self.checkpoints_enabled else ""
            if self.checkpoints_enabled and badge_plain:
                options.append(format_badge_row(clean, badge_plain, target_width=target_width))
            else:
                options.append(escape(ellipsize(clean, max(10, target_width))))
        options.append("Current state [dim](cancel rollback)[/]")
        return options

    def _apply_filter(self, query: str) -> None:
        query_clean = query.strip().lower()
        if not query_clean:
            self.filtered_entries = list(self.user_messages)
        else:
            tokens = query_clean.split()
            self.filtered_entries = [
                m for m in self.user_messages if all(t in m.text.lower() for t in tokens)
            ]
        target_w = self._row_width()
        self.filtered_options = self._format_step1_options(target_w, self.filtered_entries)
        self.filtered_items = [m.index for m in self.filtered_entries]
        self.filtered_items.append(REWIND_CURRENT_STATE)
        try:
            opt_list = self.query_one(MODAL_OPTION_LIST, OptionList)
            opt_list.clear_options()
            opt_list.add_options(self.filtered_options)
            if self.filtered_options:
                opt_list.highlighted = len(self.filtered_options) - 1
                opt_list.scroll_to_highlight()
            else:
                opt_list.highlighted = None
        except Exception:
            pass
        except Exception:
            pass

    def _refresh_options(self) -> None:
        target_w = self._row_width()
        self.raw_options = self._format_step1_options(target_w, self.user_messages)
        self.filtered_options = self._format_step1_options(target_w, self.filtered_entries)
        try:
            opt_list = self.query_one(MODAL_OPTION_LIST, OptionList)
            saved_idx = opt_list.highlighted
            opt_list.clear_options()
            opt_list.add_options(self.filtered_options)
            if saved_idx is not None and 0 <= saved_idx < len(self.filtered_options):
                opt_list.highlighted = saved_idx
            elif self.filtered_options:
                opt_list.highlighted = len(self.filtered_options) - 1
        except Exception:
            pass

        try:
            from widgets.utils.responsive import BREAKPOINT_HINT, resolve_screen_width

            screen_w = resolve_screen_width(self)
            hint_lbl = self.query_one(MODAL_HINT, Label)
            h_text = "enter • esc" if screen_w < BREAKPOINT_HINT else self.hint_text
            hint_lbl.update(h_text)
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID, classes="modal-dialog-wide"):
            yield ModalHeader(self.title, esc_hint="")
            yield Input(placeholder="Search...", id=MODAL_SEARCH_INPUT_ID, classes="modal-input")
            yield HeaderWrapOptionList(*self.filtered_options, id=self.option_list_id)
            yield ModalHint(self.hint_text, id=MODAL_HINT_ID)

    def on_mount(self) -> None:
        self._refresh_options()
        try:
            opt_list = self.query_one(MODAL_OPTION_LIST, OptionList)
            if self.filtered_options:
                default_idx = len(self.filtered_options) - 1
                if self.default_value in self.filtered_items:
                    try:
                        default_idx = self.filtered_items.index(self.default_value)
                    except Exception:
                        pass
                opt_list.highlighted = default_idx
                opt_list.scroll_to_highlight()
        except Exception:
            pass
        try:
            self.query_one(MODAL_SEARCH_INPUT, Input).focus()
        except Exception:
            try:
                opt_list = self.query_one(MODAL_OPTION_LIST, OptionList)
                opt_list.focus()
            except Exception:
                pass

    def on_input_changed(self, event: Input.Changed) -> None:
        self.search_query = event.value
        self._apply_filter(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        opt_list = self.query_one(MODAL_OPTION_LIST, OptionList)
        idx = opt_list.highlighted
        if idx is not None and 0 <= idx < len(self.filtered_items):
            self.on_option_list_option_selected(OptionList.OptionSelected(opt_list, Option(""), idx))
        elif self.filtered_items:
            self.on_option_list_option_selected(
                OptionList.OptionSelected(opt_list, Option(""), len(self.filtered_items) - 1)
            )

    async def _on_key(self, event: events.Key) -> None:
        if event.key in TAB_KEYS:
            event.prevent_default()
            event.stop()
            return
        if self._handle_search_navigation(event):
            return
        await super()._on_key(event)

    def on_resize(self, event: events.Resize) -> None:
        self._refresh_options()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        idx = event.option_index
        if idx < 0 or idx >= len(self.filtered_items):
            event.stop()
            return

        item_val = self.filtered_items[idx]
        if item_val == REWIND_CURRENT_STATE:
            self.dismiss(None)
            event.stop()
            return

        if 0 <= idx < len(self.filtered_entries):
            selected_entry = self.filtered_entries[idx]
            has_changes = bool(
                self.checkpoints_enabled
                and selected_entry.git_stats
                and selected_entry.git_stats not in ("no changes", "no checkpoint")
            )
            if not has_changes:
                self.dismiss(RewindSelection(index=selected_entry.index, restore_code=False))
                return

            try:
                app = self.app
            except Exception:
                app = getattr(self, "_app", None)
            if app:
                from widgets.presentation.screens.rewind_action import RewindActionScreen

                def on_action_done(sel: RewindSelection | None) -> None:
                    if sel is not None:
                        self.dismiss(sel)
                    else:
                        try:
                            self.query_one(MODAL_SEARCH_INPUT, Input).focus()
                        except Exception:
                            pass

                app.push_screen(
                    RewindActionScreen(
                        selected_entry,
                        session_id=self.session_id,
                        project_path=self.project_path,
                        user_messages=self.user_messages,
                    ),
                    callback=on_action_done,
                )
        event.stop()

    def action_cancel(self) -> None:
        self.dismiss(None)
