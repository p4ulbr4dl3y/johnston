from textual import events
from textual.widgets import Input, OptionList

from widgets.presentation.screens.base_modal import status_tag
from widgets.presentation.screens.base_selection import BaseSelectionScreen
from widgets.presentation.screens.constants import MODAL_SEARCH_INPUT
from widgets.utils.row_format import MODAL_MEDIUM_ROW_WIDTH, format_badge_row, option_list_row_width


class ResumeScreen(BaseSelectionScreen[str]):
    """Modal session resume screen (/resume)"""

    def __init__(self, sessions: list[dict], current_session_id: str | None = None):
        self.sessions = sessions
        self.current_session_id = current_session_id
        self.has_active = bool(
            current_session_id and any(str(s.get("id")) == str(current_session_id) for s in sessions)
        )
        items = [str(s.get("id")) for s in sessions]

        if current_session_id and str(current_session_id) in items:
            default_val = str(current_session_id)
        else:
            default_val = items[0] if items else ""

        # Pre-format initial options with safe width
        options = self._format_all_options(MODAL_MEDIUM_ROW_WIDTH)

        super().__init__(
            title="### **Select Session to Resume**",
            options=options,
            items=items,
            default_value=default_val,
            show_search=True,
            search_placeholder="Search...",
            dialog_classes="modal-dialog-medium",
        )

    def _row_width(self) -> int:
        try:
            opt_list = self.query_one(f"#{self.option_list_id}", OptionList)
        except Exception:
            opt_list = self
        return option_list_row_width(opt_list, MODAL_MEDIUM_ROW_WIDTH)

    def _format_all_options(self, target_width: int) -> list[str]:
        options = []
        for s in self.sessions:
            sid = str(s.get("id"))
            is_active = self.has_active and sid == str(self.current_session_id)
            prefix = f"{status_tag('ACTIVE')} " if is_active else ("  " if self.has_active else "")
            title = str(s.get("title", ""))
            count = s.get("message_count", 0)
            step_str = "step" if count == 1 else "steps"
            badge_plain = f"{count} {step_str}"
            options.append(
                format_badge_row(title, badge_plain, target_width=target_width, prefix=prefix)
            )
        return options

    def _refresh_options(self) -> None:
        target_w = self._row_width()
        self.raw_options = self._format_all_options(target_w)
        try:
            search_inp = self.query_one(MODAL_SEARCH_INPUT, Input)
            query = search_inp.value
        except Exception:
            query = ""
        self._filter_options(query)

    def on_mount(self) -> None:
        super().on_mount()
        self._refresh_options()

    def on_resize(self, event: events.Resize) -> None:
        super().on_resize(event)
        self._refresh_options()

