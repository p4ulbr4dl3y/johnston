import re
import time
from typing import Generic, TypeVar

from textual import events
from textual._widget_navigation import find_first_enabled, find_last_enabled
from textual.app import ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, OptionList
from textual.widgets.option_list import Option

from widgets.presentation.screens.base_modal import BaseModalScreen
from widgets.presentation.screens.constants import (
    MODAL_DIALOG_ID,
    MODAL_HINT_ID,
    MODAL_OPTION_LIST_ID,
    MODAL_SEARCH_INPUT,
    MODAL_SEARCH_INPUT_ID,
    TAB_KEYS,
)
from widgets.presentation.widgets.modal_header import ModalHeader
from widgets.presentation.widgets.modal_hint import ModalHint
from widgets.utils.responsive import (
    MODAL_COMPACT_MAX_WIDTH,
    MODAL_MAX_WIDTH,
    MODAL_MEDIUM_MAX_WIDTH,
    MODAL_MIN_WIDTH,
    MODAL_WIDE_MAX_WIDTH,
    apply_modal_fit,
    modal_content_width,
)

T = TypeVar("T")

_NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


def _split_esc_hint(hint: str) -> tuple[str, str]:
    if not hint:
        return "", ""
    parts = [p.strip() for p in hint.split("•")]
    esc_part = ""
    action_parts = []
    for p in parts:
        lower_p = p.lower()
        if lower_p.startswith("esc") or ": close" in lower_p or ": cancel" in lower_p or ": back" in lower_p:
            esc_part = p
        else:
            action_parts.append(p)
    return " • ".join(action_parts), esc_part


class HeaderWrapOptionList(OptionList):
    """OptionList that keeps the first group's header in view on wrap-around."""

    ALLOW_SELECT = False
    _last_click_time: float = 0.0

    def _get_option_at_event(self, event: events.MouseEvent) -> int | None:
        style = getattr(event, "style", None)
        option_index = getattr(style, "meta", {}).get("option")
        if option_index is not None:
            return option_index
        try:
            line_idx = self.scroll_offset.y + event.y
            if 0 <= line_idx < len(self._lines):
                return self._lines[line_idx][0]
        except Exception:
            pass
        return None

    def _on_mouse_move(self, event: events.MouseMove) -> None:
        super()._on_mouse_move(event)
        option_index = self._get_option_at_event(event)
        if option_index is not None and 0 <= option_index < len(self.options):
            if not self.options[option_index].disabled and self.highlighted != option_index:
                self.highlighted = option_index

    def _handle_click_select(self, event: events.MouseEvent) -> None:
        now = time.time()
        if now - getattr(self, "_last_click_time", 0.0) < 0.15:
            return
        clicked_option = self._get_option_at_event(event)
        if clicked_option is None:
            clicked_option = self.highlighted
        if clicked_option is not None and 0 <= clicked_option < len(self._options):
            if not self._options[clicked_option].disabled:
                self._last_click_time = now
                self.highlighted = clicked_option
                self.action_select()

    async def _on_click(self, event: events.Click) -> None:
        self._handle_click_select(event)

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

    search_nav_input_id: str = MODAL_SEARCH_INPUT
    search_nav_option_list_id: str = ""
    search_nav_filtered_attr: str = ""

    def _handle_search_navigation(self, event: events.Key) -> bool:
        """Handle up/down keys while the search Input has focus.

        Returns True if the event was consumed, False otherwise.
        """
        if event.key not in ("down", "up"):
            return False
        try:
            inp_selector = self.search_nav_input_id if self.search_nav_input_id.startswith("#") else f"#{self.search_nav_input_id}"
            search_input = self.query_one(inp_selector, Input)
            if search_input.has_focus:
                opt_selector = self.search_nav_option_list_id if self.search_nav_option_list_id.startswith("#") else f"#{self.search_nav_option_list_id}"
                opt_list = self.query_one(opt_selector, OptionList)
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


class BaseSelectionScreen(ModalSearchNavMixin, BaseModalScreen[T], Generic[T]):
    """Base class for selection modal screens with OptionList"""

    def __init__(
        self,
        title: str,
        options: list[str],
        items: list[T],
        default_value: T,
        show_search: bool = False,
        search_placeholder: str = "Search...",
        hint_text: str = "enter: select • ↑↓: nav • esc: close",
        option_list_id: str = MODAL_OPTION_LIST_ID,
        dialog_classes: str = "",
        fit_content: bool = False,
        min_dialog_width: int = MODAL_MIN_WIDTH,
        max_dialog_width: int | None = None,
        max_options_height: int = 12,
    ):
        super().__init__()
        self.title = title
        self.raw_options = options
        self.raw_items = items
        self.default_value = default_value
        self.show_search = show_search
        self.search_placeholder = search_placeholder
        self.raw_hint_text = hint_text
        action_hint, esc_hint = _split_esc_hint(hint_text)
        self.hint_text = action_hint
        self.esc_hint = esc_hint or "esc: close"
        self.option_list_id = option_list_id
        self.dialog_classes = dialog_classes
        # Content-hugging dialog width (see widgets/utils/responsive.py):
        # small selection modals opt in instead of stretching to 90% width.
        self.fit_content = fit_content
        self.min_dialog_width = min_dialog_width
        self.max_dialog_width = max_dialog_width
        self.max_options_height = max_options_height
        self.filtered_items = list(items)
        self.filtered_options = list(options)
        self._norm_targets: dict[int, str] = {}

    def compose(self) -> ComposeResult:
        with Vertical(id=MODAL_DIALOG_ID, classes=self.dialog_classes or None):
            yield ModalHeader(self.title, esc_hint=self.esc_hint)
            if self.show_search:
                yield Input(placeholder=self.search_placeholder, id=MODAL_SEARCH_INPUT_ID)
            yield HeaderWrapOptionList(*self.filtered_options, id=self.option_list_id)
            if self.hint_text:
                yield ModalHint(self.hint_text, id=MODAL_HINT_ID)

    def on_mount(self) -> None:
        super().on_mount()
        self._apply_dialog_fit()
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

    def _apply_dialog_fit(self) -> None:
        """Hug dialog to content and budget height (mount + resize)."""
        try:
            dialog = self.query_one(f"#{MODAL_DIALOG_ID}")
        except Exception:
            return

        if getattr(self, "fit_content", False):
            content_width = modal_content_width(
                self.raw_options,
                self.title,
                self.hint_text,
                esc_hint=self.esc_hint,
            )
            max_w = getattr(self, "max_dialog_width", None)
            if max_w is None:
                classes = getattr(self, "dialog_classes", "") or ""
                if "modal-dialog-wide" in classes:
                    max_w = MODAL_WIDE_MAX_WIDTH
                elif "modal-dialog-medium" in classes or "wizard-dialog" in classes:
                    max_w = MODAL_MEDIUM_MAX_WIDTH
                elif "modal-dialog-compact" in classes:
                    max_w = MODAL_COMPACT_MAX_WIDTH
                else:
                    max_w = MODAL_MAX_WIDTH
            apply_modal_fit(
                dialog,
                content_width,
                min_width=getattr(self, "min_dialog_width", MODAL_MIN_WIDTH),
                max_width=max_w,
            )

        try:
            screen_h = self.app.size.height if getattr(self, "app", None) else 24
            if not isinstance(screen_h, int) or screen_h <= 0:
                screen_h = 24

            if screen_h < 18:
                dialog.styles.padding = (0, 1)
                dialog.styles.max_height = max(7, screen_h - 1)
                usable_h = screen_h - 1
                overhead = 6 if not self.show_search else 8
            else:
                dialog.styles.padding = (1, 2)
                dialog.styles.max_height = max(8, min(screen_h - 2, int(screen_h * 0.95)))
                usable_h = screen_h - 2
                overhead = 8 if not self.show_search else 10

            opt_list = self.query_one(f"#{self.option_list_id}", OptionList)
            max_opt_h = getattr(self, "max_options_height", 12)
            opt_list.styles.max_height = max(2, min(max_opt_h, usable_h - overhead))
        except Exception:
            pass

    def on_resize(self, event: events.Resize) -> None:
        self._apply_dialog_fit()

    def _filter_options(self, query_raw: str = "") -> None:
        """Filter options by query and update the OptionList, preserving highlight."""
        query_raw = (query_raw or "").strip().lower()
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
                        spaced = _NORMALIZE_RE.sub(" ", raw_target)
                        stripped = _NORMALIZE_RE.sub("", raw_target)
                        norm_target = f"{spaced} {stripped}"
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

        try:
            opt_list = self.query_one(f"#{self.option_list_id}", OptionList)
            saved_idx = opt_list.highlighted
            opt_list.clear_options()
            opt_list.add_options(self.filtered_options)
            if saved_idx is not None and 0 <= saved_idx < len(self.filtered_items):
                opt_list.highlighted = saved_idx
            else:
                default_idx = None
                if self.default_value is not None and self.default_value in self.filtered_items:
                    try:
                        default_idx = self.filtered_items.index(self.default_value)
                    except Exception:
                        pass
                opt_list.highlighted = default_idx
            if opt_list.highlighted is not None:
                try:
                    opt_list.scroll_to_highlight()
                except Exception:
                    pass
        except Exception:
            pass

    def on_input_changed(self, event: Input.Changed) -> None:
        self._filter_options(event.value)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        opt_list = self.query_one(f"#{self.option_list_id}", OptionList)
        idx = opt_list.highlighted
        if idx is None and self.filtered_items:
            for i, it in enumerate(self.filtered_items):
                if it is not None:
                    idx = i
                    break

        if hasattr(self, "_handle_selection"):
            self._handle_selection(idx)
            event.stop()
            event.prevent_default()
            return

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

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        if hasattr(self, "_handle_selection"):
            self._handle_selection(event.option_index)
            event.stop()
            return
        if 0 <= event.option_index < len(self.filtered_items):
            item = self.filtered_items[event.option_index]
            if item is not None:
                self.dismiss(item)
                return
            event.stop()
            return
