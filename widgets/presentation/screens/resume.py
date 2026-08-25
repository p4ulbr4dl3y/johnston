from widgets.presentation.screens.base_modal import status_tag
from widgets.presentation.screens.base_selection import BaseSelectionScreen
from widgets.utils.row_format import MODAL_MEDIUM_ROW_WIDTH, format_badge_row


class ResumeScreen(BaseSelectionScreen[str]):
    """Modal session resume screen (/resume)"""

    def __init__(self, sessions: list[dict], current_session_id: str | None = None):
        options = []
        items = []
        has_active = bool(
            current_session_id and any(str(s.get("id")) == str(current_session_id) for s in sessions)
        )

        for s in sessions:
            sid = str(s.get("id"))
            items.append(sid)
            is_active = has_active and sid == str(current_session_id)
            prefix = f"{status_tag('ACTIVE')} " if is_active else ("  " if has_active else "")
            title = str(s.get("title", ""))
            count = s.get("message_count", 0)
            step_str = "step" if count == 1 else "steps"
            badge_plain = f"{count} {step_str}"
            options.append(
                format_badge_row(title, badge_plain, target_width=MODAL_MEDIUM_ROW_WIDTH, prefix=prefix)
            )

        if current_session_id and str(current_session_id) in items:
            default_val = str(current_session_id)
        else:
            default_val = items[0] if items else ""

        super().__init__(
            title="### **Select Session to Resume**",
            options=options,
            items=items,
            default_value=default_val,
            show_search=True,
            search_placeholder="Search...",
            dialog_classes="modal-dialog-medium",
        )
