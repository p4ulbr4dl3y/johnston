"""UI message-visibility policy.

Rendering decision for whether a user message should appear in the ChatView.
This is presentation-layer policy and deliberately lives in ``widgets`` rather
than the domain, so the domain stays free of UI markers (``show_in_ui``) and
rendered label prefixes (``[System Notification]`` / ``[System Note:``).
"""


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
