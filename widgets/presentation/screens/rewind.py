from dataclasses import dataclass
from typing import Optional

from rich.markup import escape
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, Label, Markdown, OptionList, Static
from textual.widgets.option_list import Option

from core.application.session.actions import RewindEntry
from widgets.presentation.screens.base_modal import BaseModalScreen
from widgets.presentation.screens.base_selection import HeaderWrapOptionList, ModalSearchNavMixin
from widgets.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT,
    MODAL_HINT_ID,
    MODAL_MARKDOWN,
    MODAL_MARKDOWN_CENTERED,
    MODAL_OPTION_LIST,
    MODAL_OPTION_LIST_ID,
    MODAL_SEARCH_INPUT,
    MODAL_SEARCH_INPUT_ID,
    TAB_KEYS,
)
from widgets.utils.row_format import MODAL_WIDE_ROW_WIDTH, ellipsize, format_badge_row, option_list_row_width


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
    t.append("Files to revert", style="#ffffff")
    if stat_label:
        t.append(stat_label, style="#a1a1aa")
    t.append(":\n", style="#ffffff")

    lines: list[tuple[str, str]] = []
    for f in changed_files[:max_show]:
        display_f = ellipsize(f, max(15, max_width - 4)) if max_width > 0 else f
        lines.append((f"  {display_f}", "#a1a1aa"))

    if len(changed_files) > max_show:
        rem = len(changed_files) - max_show
        lines.append((f"  ... and {rem} more", "italic #71717a"))

    for i, (line_text, line_style) in enumerate(lines):
        t.append(line_text, style=line_style)
        if i < len(lines) - 1:
            t.append("\n")

    return t


class RewindScreen(ModalSearchNavMixin, BaseModalScreen[Optional[RewindSelection]]):
    """Modal rollback screen (/rewind) with 2-step selection for code vs conversation."""

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
        self.step = 1
        self.search_query = ""
        self.selected_entry: Optional[RewindEntry] = None
        self.selected_step1_index: Optional[int] = None
        self.filtered_entries: list[RewindEntry] = list(user_messages)

        options = self._format_step1_options(MODAL_WIDE_ROW_WIDTH, self.filtered_entries)

        self.title = "### **Select Message to Rollback To**"
        self.hint_text = "enter: select • ↑↓: nav • esc: cancel"
        self.raw_options = list(options)
        self.raw_items = [m.index for m in user_messages]
        self.filtered_options = list(options)
        self.filtered_items = list(self.raw_items)
        self.default_value = self.raw_items[-1] if self.raw_items else -1
        self.option_list_id = MODAL_OPTION_LIST_ID

    def _row_width(self) -> int:
        try:
            opt_list = self.query_one(MODAL_OPTION_LIST, OptionList)
        except Exception:
            opt_list = self
        return option_list_row_width(opt_list, MODAL_WIDE_ROW_WIDTH)

    def _format_step1_options(self, target_width: int, entries: Optional[list[RewindEntry]] = None) -> list[str]:
        options = []
        msg_list = entries if entries is not None else self.user_messages
        for msg in msg_list:
            text = msg.text
            diff_stat = msg.git_stats
            clean = " ".join(text.replace("\n", " ").replace("\r", " ").split())
            opt_text = clean or "(empty message)"
            if self.checkpoints_enabled:
                badge_plain = diff_stat or "no checkpoint"
                opt = format_badge_row(opt_text, badge_plain, target_width=target_width)
            else:
                opt = escape(ellipsize(opt_text, max(10, target_width - 5)))
            options.append(opt)
        return options

    def _format_step2_options(self, target_width: int) -> list[str]:
        return [
            "Rollback conversation & files [dim #71717a](revert code)[/]",
            "Rollback conversation only [dim #71717a](keep current code)[/]",
            "View changes diff [dim #71717a](inspect code changes)[/]",
        ]

    def _apply_filter(self, query: str = "") -> None:
        q = (query or "").strip().lower()
        target_w = self._row_width()
        self.raw_options = self._format_step1_options(target_w, self.user_messages)
        if not q:
            self.filtered_entries = list(self.user_messages)
        else:
            tokens = q.split()
            self.filtered_entries = [
                msg
                for msg in self.user_messages
                if all(t in f"{msg.text} {msg.git_stats}".lower() for t in tokens)
            ]
        self.filtered_options = self._format_step1_options(target_w, self.filtered_entries)
        self.filtered_items = [m.index for m in self.filtered_entries]

        try:
            opt_list = self.query_one(MODAL_OPTION_LIST, OptionList)
            saved_idx = opt_list.highlighted
            opt_list.clear_options()
            opt_list.add_options(self.filtered_options)
            if saved_idx is not None and 0 <= saved_idx < len(self.filtered_options):
                opt_list.highlighted = saved_idx
            elif self.filtered_options:
                opt_list.highlighted = len(self.filtered_options) - 1
            else:
                opt_list.highlighted = None
        except Exception:
            pass

    def _refresh_options(self) -> None:
        target_w = self._row_width()
        if self.step == 1:
            self._apply_filter(self.search_query)
        else:
            self.filtered_options = self._format_step2_options(target_w)
            try:
                opt_list = self.query_one(MODAL_OPTION_LIST, OptionList)
                saved_idx = opt_list.highlighted
                opt_list.clear_options()
                opt_list.add_options(self.filtered_options)
                if saved_idx is not None and 0 <= saved_idx < len(self.filtered_options):
                    opt_list.highlighted = saved_idx
            except Exception:
                pass

        try:
            from widgets.utils.responsive import BREAKPOINT_HINT, resolve_screen_width

            screen_w = resolve_screen_width(self)
            hint_lbl = self.query_one(MODAL_HINT, Label)
            if self.step == 1:
                h_text = "enter • ↑↓ • esc" if screen_w < BREAKPOINT_HINT else self.hint_text
            else:
                h_text = "enter • ↑↓ • esc: back" if screen_w < BREAKPOINT_HINT else "enter: select • ↑↓: nav • esc: back to messages"
            hint_lbl.update(h_text)
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID, classes="modal-dialog-wide"):
            yield Markdown(self.title, classes=f"{MODAL_MARKDOWN} {MODAL_MARKDOWN_CENTERED}")
            yield Input(placeholder="Search...", id=MODAL_SEARCH_INPUT_ID)
            yield Static("", id="rewind-files", classes=MODAL_MARKDOWN, markup=False)
            yield HeaderWrapOptionList(*self.filtered_options, id=self.option_list_id)
            yield Label(self.hint_text, id=MODAL_HINT_ID)

    def on_mount(self) -> None:
        try:
            self.query_one("#rewind-files", Static).display = False
        except Exception:
            pass
        self._refresh_options()
        try:
            self.query_one(MODAL_SEARCH_INPUT, Input).focus()
        except Exception:
            try:
                opt_list = self.query_one(MODAL_OPTION_LIST, OptionList)
                opt_list.focus()
            except Exception:
                pass

    def on_input_changed(self, event: Input.Changed) -> None:
        if self.step == 1:
            self.search_query = event.value
            self._apply_filter(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self.step == 1:
            opt_list = self.query_one(MODAL_OPTION_LIST, OptionList)
            idx = opt_list.highlighted
            if idx is not None and 0 <= idx < len(self.filtered_entries):
                self.on_option_list_option_selected(OptionList.OptionSelected(opt_list, Option(""), idx))
            elif self.filtered_entries:
                self.on_option_list_option_selected(OptionList.OptionSelected(opt_list, Option(""), 0))

    def _on_key(self, event: events.Key) -> None:
        if self.step == 1:
            if event.key in TAB_KEYS:
                event.prevent_default()
                event.stop()
                return
            if self._handle_search_navigation(event):
                return

    def _update_step2_display(self) -> None:
        if self.step != 2 or not self.selected_entry:
            return
        clean = " ".join(self.selected_entry.text.replace("\n", " ").replace("\r", " ").split())
        target_w = self._row_width()
        clean_preview = ellipsize(clean, max(12, target_w - 12)) if clean else "(empty message)"

        try:
            md = self.query_one(f".{MODAL_MARKDOWN}", Markdown)
            md.update(f"### **Rollback: {clean_preview}**")
        except Exception:
            pass

        try:
            files_widget = self.query_one("#rewind-files", Static)
            if self.selected_entry.changed_files:
                files_widget.update(
                    format_rewind_files(
                        self.selected_entry.changed_files,
                        self.selected_entry.git_stats,
                        max_width=target_w,
                    )
                )
                files_widget.display = True
            else:
                files_widget.display = False
        except Exception:
            pass

    def on_resize(self, event: events.Resize) -> None:
        self._refresh_options()
        self._update_step2_display()

    def _show_step_2(self, entry: RewindEntry) -> None:
        self.step = 2
        self.selected_entry = entry
        self.filtered_items = ["both", "conversation", "diff"]
        try:
            self.query_one(MODAL_SEARCH_INPUT, Input).display = False
        except Exception:
            pass
        self._refresh_options()
        self._update_step2_display()
        try:
            opt_list = self.query_one(MODAL_OPTION_LIST, OptionList)
            opt_list.highlighted = 0
            opt_list.focus()
        except Exception:
            pass

    def _open_diff_viewer(self, entry: RewindEntry) -> None:
        from core.infrastructure.storage.git_checkpoint import GitCheckpointManager
        from widgets.presentation.screens.diff import DiffScreen

        seq_idx = 0
        for i, m in enumerate(self.user_messages):
            if m.index == entry.index:
                seq_idx = i
                break

        diff_items = []
        if self.session_id:
            try:
                diff_items = GitCheckpointManager.get_checkpoint_diff(
                    self.session_id, seq_idx, project_path=self.project_path
                )
            except Exception:
                diff_items = []

        clean = " ".join(entry.text.replace("\n", " ").replace("\r", " ").split())
        clean_preview = ellipsize(clean, 60) if clean else "(empty message)"

        try:
            app = self.app
        except Exception:
            app = None

        if app:
            app.push_screen(DiffScreen(diff_items, title=f"Rollback: {clean_preview}", from_rewind=True))

    def _show_step_1(self) -> None:
        self.step = 1
        self.selected_entry = None

        try:
            md = self.query_one(f".{MODAL_MARKDOWN}", Markdown)
            md.update(self.title)
        except Exception:
            pass

        try:
            files_widget = self.query_one("#rewind-files", Static)
            files_widget.display = False
        except Exception:
            pass

        try:
            search_inp = self.query_one(MODAL_SEARCH_INPUT, Input)
            search_inp.display = True
            search_inp.focus()
        except Exception:
            pass

        self._refresh_options()

        try:
            hint = self.query_one(MODAL_HINT, Label)
            hint.update(self.hint_text)
        except Exception:
            pass

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        idx = event.option_index
        if idx < 0 or idx >= len(self.filtered_items):
            event.stop()
            return

        if self.step == 1:
            self.selected_step1_index = idx
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
                self._show_step_2(selected_entry)
            event.stop()
            return
        elif self.step == 2:
            action = self.filtered_items[idx]
            if action == "both" and self.selected_entry is not None:
                self.dismiss(RewindSelection(index=self.selected_entry.index, restore_code=True))
            elif action == "conversation" and self.selected_entry is not None:
                self.dismiss(RewindSelection(index=self.selected_entry.index, restore_code=False))
            elif action == "diff" and self.selected_entry is not None:
                self._open_diff_viewer(self.selected_entry)
            event.stop()
            return

    def action_cancel(self) -> None:
        if self.step == 2:
            self._show_step_1()
        else:
            self.dismiss(None)
