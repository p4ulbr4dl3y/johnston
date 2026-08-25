import os
from typing import Optional

from rich.markup import escape
from rich.table import Table
from rich.text import Text
from textual import events
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Input, OptionList, Static

from widgets.chat_toolcall import ToolScrollBox
from widgets.mixins.resize_debounce import ResizeDebounceMixin
from widgets.presentation.screens.base_selection import ModalSearchNavMixin
from widgets.presentation.widgets.chat_diff import format_edit_diff
from widgets.utils.key_aliases import expand_bindings
from widgets.utils.responsive import BREAKPOINT_COMPACT, BREAKPOINT_HINT, is_compact_width, resolve_width
from widgets.utils.row_format import DIFF_SIDEBAR_ROW_WIDTH, display_width


class DiffHeader(ResizeDebounceMixin, Static):
    """Header widget for the full-screen diff viewer with responsive width adaptation."""

    def __init__(
        self,
        title: str,
        stats_summary: str,
        from_rewind: bool = False,
        id: Optional[str] = None,
        classes: Optional[str] = None,
    ):
        super().__init__(id=id, classes=classes)
        self.title_text = title
        self.stats_summary = stats_summary
        self.from_rewind = from_rewind

    def on_mount(self) -> None:
        self.render_header()

    def render_header(self) -> None:
        table = Table.grid(expand=True)
        table.add_column(ratio=1, justify="left")
        table.add_column(justify="right")

        width = resolve_width(self)
        esc_label = "esc: back" if self.from_rewind else "esc: close"

        if is_compact_width(width, breakpoint=BREAKPOINT_COMPACT):
            left_text = (
                f"[bold #ffffff]Diff[/]  [#71717a]•[/]  "
                f"[#f4f4f5]{escape(self.title_text[:20])}[/]  "
                f"[#71717a]({escape(self.stats_summary)})[/]"
            )
            right_text = "[#71717a]esc[/]"
        else:
            left_text = (
                f"[bold #ffffff]Diff Viewer[/]  [#71717a]•[/]  "
                f"[#f4f4f5]{escape(self.title_text)}[/]  [#71717a]•[/]  "
                f"[#71717a]({escape(self.stats_summary)})[/]"
            )
            right_text = f"[#71717a]{esc_label}[/]"

        table.add_row(left_text, right_text)
        self.update(table)

    def render_for_size(self) -> None:
        self.render_header()


def format_relative_path(path: str, max_length: int = 40) -> str:
    """Format relative file path with middle truncation if long."""
    if not path:
        return ""
    if len(path) <= max_length:
        return path
    parts = path.split(os.sep if os.sep in path else "/")
    if len(parts) > 3:
        shortened = f"{parts[0]}/{parts[1]}/.../{parts[-1]}"
        if len(shortened) <= max_length:
            return shortened
    if len(parts) >= 2:
        return f"{parts[0]}/.../{parts[-1]}"
    return path[: max_length - 3] + "..."


class DiffFooter(ResizeDebounceMixin, Static):
    """Footer widget for the full-screen diff viewer with responsive width adaptation."""

    def __init__(self, id: Optional[str] = None, classes: Optional[str] = None):
        super().__init__(id=id, classes=classes)
        self.current_file = ""
        self.current_stats = ""
        self.is_compact = False
        self.compact_view = "files"

    def on_mount(self) -> None:
        self.render_footer()

    def set_view_context(self, is_compact: bool, compact_view: str) -> None:
        self.is_compact = is_compact
        self.compact_view = compact_view
        self.render_footer()

    def update_info(self, file_path: str, stats: str) -> None:
        self.current_file = file_path
        self.current_stats = stats
        self.render_footer()

    def render_for_size(self) -> None:
        self.render_footer()

    def render_footer(self) -> None:
        table = Table.grid(expand=True)
        table.add_column(ratio=1, justify="left")
        table.add_column(justify="right")

        width = resolve_width(self)

        max_path_len = min(45, max(18, width // 3))

        if self.current_file:
            display_path = format_relative_path(self.current_file, max_length=max_path_len)
            left_text = f"[bold #f4f4f5]{escape(display_path)}[/]  [#71717a]({escape(self.current_stats)})[/]"
        else:
            left_text = "[dim #71717a]No file selected[/]"

        if is_compact_width(width, breakpoint=BREAKPOINT_COMPACT):
            if self.compact_view == "diff":
                right_text = "[#71717a]esc: files  •  pgup/pgdn: scroll[/]"
            else:
                right_text = "[#71717a]enter: view diff  •  esc: close[/]"
        elif width >= BREAKPOINT_HINT:
            right_text = "[#71717a]↑↓: files  •  tab: toggle sidebar  •  pgup/pgdn: scroll[/]"
        else:
            right_text = "[#71717a]↑↓: files  •  tab: sidebar[/]"

        table.add_row(left_text, right_text)
        self.update(table)


class DiffScreen(ModalSearchNavMixin, Screen[None]):
    """Full-screen Git Diff Viewer matching Johnston's zinc monochrome design."""

    ALLOW_SELECT = False
    inherit_bindings = False
    search_nav_input_id = "diff-search-input"
    search_nav_option_list_id = "diff-file-list"
    search_nav_filtered_attr = "filtered_indices"

    BINDINGS = expand_bindings([
        ("escape", "close", "Close"),
        ("tab", "toggle_sidebar", "Toggle Sidebar"),
        ("b", "toggle_sidebar", "Toggle Sidebar"),
        ("pageup", "page_up", "Page Up"),
        ("pagedown", "page_down", "Page Down"),
        ("ctrl+c", "quit_app", "Quit"),
        ("ctrl+q", "quit_app", "Quit"),
    ])

    def __init__(
        self,
        diff_items: list[tuple[str, str, int, int]],
        title: str = "Session Changes",
        from_rewind: bool = False,
    ):
        super().__init__()
        self.diff_items = diff_items
        self.title_text = title
        self.from_rewind = from_rewind
        self.selected_index = 0
        self.sidebar_visible = True
        self.compact_view = "files"

        total_added = sum(item[2] for item in diff_items)
        total_deleted = sum(item[3] for item in diff_items)
        files_count = len(diff_items)

        if files_count == 0:
            self.stats_summary = "no changes"
        else:
            plural = "files" if files_count != 1 else "file"
            self.stats_summary = f"{files_count} {plural}, +{total_added} / -{total_deleted}"

        self.filtered_indices: list[int] = list(range(len(self.diff_items)))
        self.sidebar_options: list[str] = self._format_sidebar_options(DIFF_SIDEBAR_ROW_WIDTH)

    def _format_sidebar_options(self, target_width: int = DIFF_SIDEBAR_ROW_WIDTH) -> list[str]:
        options = []
        for file_path, _, added, deleted in self.diff_items:
            short_name = os.path.basename(file_path) or file_path
            stat_plain = f"+{added}/-{deleted}"
            if display_width(short_name) + display_width(stat_plain) + 1 > target_width:
                max_name_len = max(4, target_width - display_width(stat_plain) - 1)
                dot_idx = short_name.rfind(".")
                if dot_idx > 3 and len(short_name) - dot_idx <= 5:
                    ext = short_name[dot_idx:]
                    base = short_name[:dot_idx]
                    short_name = base[: max_name_len - display_width(ext) - 1] + "…" + ext
                else:
                    short_name = short_name[: max_name_len - 1] + "…"

            spaces = " " * max(1, target_width - display_width(short_name) - display_width(stat_plain))
            stat_markup = f"[#22c55e]+{added}[/][dim #71717a]/[/][#ef4444]-{deleted}[/]"
            options.append(f"{escape(short_name)}{spaces}{stat_markup}")
        return options

    def _sidebar_row_width(self) -> int:
        try:
            sidebar = self.query_one("#diff-sidebar", Vertical)
            width = sidebar.size.width
            if isinstance(width, int) and width > 15:
                return max(15, width - 3)
        except Exception:
            pass
        return DIFF_SIDEBAR_ROW_WIDTH

    def _refresh_sidebar_options(self) -> None:
        target_w = self._sidebar_row_width()
        self.sidebar_options = self._format_sidebar_options(target_w)
        try:
            opt_list = self.query_one("#diff-file-list", OptionList)
            saved_hl = opt_list.highlighted
            opt_list.clear_options()
            opt_list.add_options([self.sidebar_options[i] for i in self.filtered_indices])
            if saved_hl is not None and 0 <= saved_hl < len(self.filtered_indices):
                opt_list.highlighted = saved_hl
        except Exception:
            pass

    def _update_layout(self) -> None:
        width = resolve_width(self)
        try:
            sidebar = self.query_one("#diff-sidebar", Vertical)
            content = self.query_one("#diff-content-container", Vertical)
        except Exception:
            return

        is_compact = is_compact_width(width, breakpoint=BREAKPOINT_COMPACT)
        if is_compact:
            if self.compact_view == "diff":
                sidebar.add_class("-hidden")
                sidebar.remove_class("-full-width")
                content.remove_class("-hidden")
                content.add_class("-full-width")
            else:
                sidebar.remove_class("-hidden")
                sidebar.add_class("-full-width")
                content.add_class("-hidden")
                content.remove_class("-full-width")
        else:
            sidebar.remove_class("-full-width")
            content.remove_class("-full-width")
            if self.sidebar_visible:
                sidebar.remove_class("-hidden")
            else:
                sidebar.add_class("-hidden")
            content.remove_class("-hidden")

        self._refresh_sidebar_options()

        try:
            footer = self.query_one("#diff-footer", DiffFooter)
            footer.set_view_context(is_compact=is_compact, compact_view=self.compact_view)
        except Exception:
            pass

    def compose(self) -> ComposeResult:
        with Vertical(id="diff-container"):
            yield DiffHeader(self.title_text, self.stats_summary, from_rewind=self.from_rewind, id="diff-header")
            with Horizontal(id="diff-body"):
                with Vertical(id="diff-sidebar"):
                    yield Input(placeholder="Search files...", id="diff-search-input")
                    yield OptionList(*self.sidebar_options, id="diff-file-list")
                with Vertical(id="diff-content-container"):
                    if not self.diff_items:
                        with Vertical(id="diff-empty-container"):
                            yield Static("[dim #71717a]No workspace changes found.[/]", id="diff-empty-label")
                    else:
                        with ToolScrollBox(id="diff-scroll-box"):
                            yield Static(id="diff-content-view")
            yield DiffFooter(id="diff-footer")

    def on_mount(self) -> None:
        self._update_layout()
        if self.diff_items:
            try:
                search_input = self.query_one("#diff-search-input", Input)
                search_input.focus()
            except Exception:
                pass
            self._render_current_diff(0)
        else:
            try:
                footer = self.query_one("#diff-footer", DiffFooter)
                footer.update_info("", "no changes")
            except Exception:
                pass

    def on_resize(self, event: events.Resize) -> None:
        self._update_layout()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id != "diff-search-input":
            return
        query = (event.value or "").strip().lower()
        if not query:
            self.filtered_indices = list(range(len(self.diff_items)))
        else:
            self.filtered_indices = [
                idx
                for idx, item in enumerate(self.diff_items)
                if query in item[0].lower() or query in (os.path.basename(item[0]) or "").lower()
            ]

        try:
            opt_list = self.query_one("#diff-file-list", OptionList)
            opt_list.clear_options()
            opt_list.add_options([self.sidebar_options[i] for i in self.filtered_indices])
            if self.filtered_indices:
                opt_list.highlighted = 0
                self._render_current_diff(self.filtered_indices[0])
            else:
                opt_list.highlighted = None
                self._render_empty_search()
        except Exception:
            pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if self.filtered_indices:
            width = resolve_width(self)
            if is_compact_width(width, breakpoint=BREAKPOINT_COMPACT):
                self.compact_view = "diff"
                self._update_layout()

    def _render_empty_search(self) -> None:
        try:
            content_view = self.query_one("#diff-content-view", Static)
            content_view.update("[dim #71717a]No matching files found.[/]")
            footer = self.query_one("#diff-footer", DiffFooter)
            footer.update_info("", "no matches")
        except Exception:
            pass

    def _render_current_diff(self, index: int) -> None:
        if not (0 <= index < len(self.diff_items)):
            return

        self.selected_index = index
        file_path, diff_text, added, deleted = self.diff_items[index]

        try:
            formatted = format_edit_diff(diff_text, file_path)
            content_view = self.query_one("#diff-content-view", Static)
            content_view.update(formatted)
        except Exception:
            try:
                content_view = self.query_one("#diff-content-view", Static)
                content_view.update(Text(diff_text))
            except Exception:
                pass

        try:
            scroll_box = self.query_one("#diff-scroll-box", ToolScrollBox)
            scroll_box.scroll_home(animate=False)
        except Exception:
            pass

        try:
            footer = self.query_one("#diff-footer", DiffFooter)
            footer.update_info(file_path, f"+{added} / -{deleted}")
        except Exception:
            pass

    def on_option_list_option_highlighted(self, event: OptionList.OptionHighlighted) -> None:
        if event.option_index is not None and 0 <= event.option_index < len(self.filtered_indices):
            real_idx = self.filtered_indices[event.option_index]
            self._render_current_diff(real_idx)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if event.option_index is not None and 0 <= event.option_index < len(self.filtered_indices):
            real_idx = self.filtered_indices[event.option_index]
            self._render_current_diff(real_idx)
            width = resolve_width(self)
            if is_compact_width(width, breakpoint=BREAKPOINT_COMPACT):
                self.compact_view = "diff"
                self._update_layout()

    def action_toggle_sidebar(self) -> None:
        width = resolve_width(self)
        if is_compact_width(width, breakpoint=BREAKPOINT_COMPACT):
            self.compact_view = "diff" if self.compact_view == "files" else "files"
        else:
            self.sidebar_visible = not self.sidebar_visible
        self._update_layout()

    def action_page_up(self) -> None:
        try:
            scroll_box = self.query_one("#diff-scroll-box", ToolScrollBox)
            scroll_box.scroll_page_up(animate=False)
        except Exception:
            pass

    def action_page_down(self) -> None:
        try:
            scroll_box = self.query_one("#diff-scroll-box", ToolScrollBox)
            scroll_box.scroll_page_down(animate=False)
        except Exception:
            pass

    def _on_key(self, event: events.Key) -> None:
        if self._handle_search_navigation(event):
            return
        if event.key in ("pageup", "pagedown"):
            try:
                scroll_box = self.query_one("#diff-scroll-box", ToolScrollBox)
                if event.key == "pageup":
                    scroll_box.scroll_page_up(animate=False)
                else:
                    scroll_box.scroll_page_down(animate=False)
                event.prevent_default()
                event.stop()
            except Exception:
                pass

    def action_close(self) -> None:
        width = resolve_width(self)
        if is_compact_width(width, breakpoint=BREAKPOINT_COMPACT) and self.compact_view == "diff":
            self.compact_view = "files"
            self._update_layout()
            try:
                self.query_one("#diff-search-input", Input).focus()
            except Exception:
                pass
            return
        self.dismiss(None)

    def action_quit_app(self) -> None:
        try:
            if self.app:
                self.app.exit()
        except Exception:
            pass
