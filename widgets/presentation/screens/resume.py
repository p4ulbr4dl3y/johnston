from textual import events
from textual.widgets import Input, Label, Markdown, OptionList

from widgets.presentation.screens.base_modal import status_tag
from widgets.presentation.screens.base_selection import BaseSelectionScreen
from widgets.presentation.screens.constants import (
    MODAL_HINT_ID,
    MODAL_MARKDOWN,
    MODAL_SEARCH_INPUT,
)
from widgets.utils.row_format import (
    MODAL_WIDE_ROW_WIDTH,
    format_badge_row,
    option_list_row_width,
)


def _order_sessions_hierarchically(sessions: list[dict]) -> list[dict]:
    parent_map: dict[str, list[dict]] = {}
    roots: list[dict] = []
    session_ids = {str(s.get("id")) for s in sessions}

    for s in sessions:
        pid = s.get("parent_id")
        if pid and str(pid) in session_ids:
            parent_map.setdefault(str(pid), []).append(s)
        else:
            roots.append(s)

    ordered = []
    for root in roots:
        ordered.append(root)
        children = parent_map.get(str(root.get("id")), [])
        ordered.extend(children)
    return ordered


class ResumeScreen(BaseSelectionScreen[str]):
    """Modal session resume screen (/resume) with in-place 2-step conflict resolution."""

    def __init__(
        self,
        sessions: list[dict],
        current_session_id: str | None = None,
        initial_selected_id: str | None = None,
    ):
        ordered_sessions = _order_sessions_hierarchically(sessions)
        self.sessions = ordered_sessions
        self.current_session_id = current_session_id
        self.has_active = bool(
            current_session_id and any(str(s.get("id")) == str(current_session_id) for s in ordered_sessions)
        )
        items = [str(s.get("id")) for s in ordered_sessions]

        highlight_target = initial_selected_id or current_session_id
        if highlight_target and str(highlight_target) in items:
            default_val = str(highlight_target)
        else:
            default_val = items[0] if items else ""

        self.step = 1
        self.selected_session: dict | None = None
        self.selected_step1_index: int | None = None

        # Pre-format initial options with safe width
        options = self._format_all_options(MODAL_WIDE_ROW_WIDTH)

        super().__init__(
            title="### **Select Session to Resume**",
            options=options,
            items=items,
            default_value=default_val,
            show_search=True,
            search_placeholder="Search...",
            dialog_classes="modal-dialog-wide",
        )

    def _row_width(self) -> int:
        try:
            opt_list = self.query_one(f"#{self.option_list_id}", OptionList)
        except Exception:
            opt_list = self
        return option_list_row_width(opt_list, MODAL_WIDE_ROW_WIDTH)

    def _format_all_options(self, target_width: int) -> list[str]:
        options = []
        has_indicator = self.has_active or any(s.get("is_locked") for s in self.sessions)
        session_ids = {str(s.get("id")) for s in self.sessions}
        for s in self.sessions:
            sid = str(s.get("id"))
            is_active = self.has_active and sid == str(self.current_session_id)
            is_locked = bool(s.get("is_locked")) and not is_active
            is_fork = bool(s.get("parent_id") and str(s.get("parent_id")) in session_ids)

            if is_active:
                status_pfx = f"{status_tag('ACTIVE')} "
            elif is_locked:
                status_pfx = f"{status_tag('LOCKED')} "
            else:
                status_pfx = "  " if has_indicator else ""

            branch_pfx = "[dim]└─ [/]" if is_fork else ""
            prefix = f"{status_pfx}{branch_pfx}"
            title = str(s.get("title", ""))
            count = s.get("message_count", 0)
            step_str = "step" if count == 1 else "steps"
            badge_plain = f"{count} {step_str}"
            options.append(
                format_badge_row(title, badge_plain, target_width=target_width, prefix=prefix)
            )
        return options

    def _format_step2_options(self) -> list[str]:
        return [
            "Open read-only [dim](fork on edit)[/]",
            "Steal session [dim](take over)[/]",
        ]

    def _refresh_options(self) -> None:
        if self.step == 1:
            target_w = self._row_width()
            self.raw_options = self._format_all_options(target_w)
            try:
                search_inp = self.query_one(MODAL_SEARCH_INPUT, Input)
                query = search_inp.value
            except Exception:
                query = ""
            self._filter_options(query)
        else:
            self.filtered_options = self._format_step2_options()
            try:
                opt_list = self.query_one(f"#{self.option_list_id}", OptionList)
                saved_idx = opt_list.highlighted
                opt_list.clear_options()
                opt_list.add_options(self.filtered_options)
                if saved_idx is not None and 0 <= saved_idx < len(self.filtered_options):
                    opt_list.highlighted = saved_idx
            except Exception:
                pass

    def on_mount(self) -> None:
        self._apply_dialog_fit()
        super().on_mount()
        self._refresh_options()

    def on_resize(self, event: events.Resize) -> None:
        self._apply_dialog_fit()
        self._refresh_options()

    def _show_step_2(self, session_dict: dict) -> None:
        self.step = 2
        self.selected_session = session_dict

        title = "### **Session is Open in Another Terminal**"
        try:
            md = self.query_one(f".{MODAL_MARKDOWN}", Markdown)
            md.update(title)
        except Exception:
            pass

        try:
            search_inp = self.query_one(MODAL_SEARCH_INPUT, Input)
            search_inp.display = False
        except Exception:
            pass

        try:
            hint_lbl = self.query_one(f"#{MODAL_HINT_ID}", Label)
            hint_lbl.update("enter: select • ↑↓: nav • esc: back")
        except Exception:
            pass

        self.filtered_items = ["readonly", "steal"]
        self._refresh_options()
        try:
            opt_list = self.query_one(f"#{self.option_list_id}", OptionList)
            opt_list.highlighted = 0
            opt_list.focus()
        except Exception:
            pass

    def _show_step_1(self) -> None:
        self.step = 1
        self.selected_session = None

        try:
            md = self.query_one(f".{MODAL_MARKDOWN}", Markdown)
            md.update(self.title)
        except Exception:
            pass

        try:
            search_inp = self.query_one(MODAL_SEARCH_INPUT, Input)
            search_inp.display = True
        except Exception:
            pass

        try:
            hint_lbl = self.query_one(f"#{MODAL_HINT_ID}", Label)
            hint_lbl.update(self.hint_text)
        except Exception:
            pass

        self.filtered_items = [str(s.get("id")) for s in self.sessions]
        self._refresh_options()
        try:
            opt_list = self.query_one(f"#{self.option_list_id}", OptionList)
            if self.selected_step1_index is not None and 0 <= self.selected_step1_index < len(self.filtered_options):
                opt_list.highlighted = self.selected_step1_index
            if self.show_search:
                self.query_one(MODAL_SEARCH_INPUT, Input).focus()
            else:
                opt_list.focus()
        except Exception:
            pass

    def _on_key(self, event: events.Key) -> None:
        if self.step == 2 and event.key == "escape":
            self._show_step_1()
            event.prevent_default()
            event.stop()
            return
        super()._on_key(event)

    def _handle_selection(self, idx: int | None) -> None:
        if idx is None or idx < 0 or idx >= len(self.filtered_items):
            return

        if self.step == 1:
            self.selected_step1_index = idx
            sid = self.filtered_items[idx]
            sess = next((s for s in self.sessions if str(s.get("id")) == str(sid)), None)
            if sess and sess.get("is_locked"):
                self._show_step_2(sess)
                return
            self.dismiss(sid)
        elif self.step == 2:
            choice = self.filtered_items[idx]
            sid = str(self.selected_session.get("id")) if self.selected_session else ""
            self.dismiss(f"{choice}:{sid}")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        event.prevent_default()
        try:
            opt_list = self.query_one(f"#{self.option_list_id}", OptionList)
            idx = opt_list.highlighted
        except Exception:
            idx = 0
        if idx is None and self.filtered_items:
            idx = 0
        self._handle_selection(idx)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        event.prevent_default()
        self._handle_selection(event.option_index)

