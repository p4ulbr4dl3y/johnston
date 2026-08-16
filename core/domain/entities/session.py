"""Pure session domain constants and trivial helpers.

No IO, no agent access. Imported directly by consumers across core and UI.
"""

from typing import Any

MAIN_STATUS_ACTIVE = "active"
SUBAGENT_STATUS_RUNNING = "running"
STATUS_COMPLETED = "completed"
STATUS_CANCELLED = "cancelled"
STATUS_ERROR = "error"


def _coerce_int(val: Any) -> int:
    """Coerce a persisted token count to int, tolerating None/invalid types."""
    if val is None or isinstance(val, bool):
        return 0
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


def _coerce_float(val: Any) -> float:
    """Coerce a persisted cost value to float, tolerating None/invalid types."""
    if val is None or isinstance(val, bool):
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def is_ui_visible_user_message(msg: dict) -> bool:
    """Return True if a user message should be rendered in the ChatView UI."""
    if not isinstance(msg, dict):
        return False
    if msg.get("show_in_ui") is False:
        return False
    text = msg.get("text", "")
    if text.startswith(("[System Notification]", "[System Note:")):
        return False
    return True
