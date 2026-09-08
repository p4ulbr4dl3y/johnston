"""Subagent UI toolcard tracking and status synchronization."""
from typing import Any


def record_subagent_session(app: Any, session_id: str) -> None:
    """Associate a spawned subagent's session id with the host's current tool widget."""
    if app is None:
        return
    widget = getattr(app, "current_tool_widget", None)
    if widget is None:
        return
    if isinstance(getattr(widget, "args", None), dict):
        widget.args["session_id"] = session_id
    try:
        setattr(widget, "subagent_session_id", session_id)
    except Exception:
        pass
    reg = getattr(app, "_subagent_tools", None)
    if not isinstance(reg, dict):
        reg = {}
        app._subagent_tools = reg
    reg[session_id] = widget


def mark_subagent_running(app: Any, session_id: str, text: str = "") -> None:
    """Flip the host's invoke_subagent widget for session_id back to running (yellow)."""
    if app is None:
        return
    reg = getattr(app, "_subagent_tools", None)
    if not isinstance(reg, dict):
        return
    widget = reg.get(session_id)
    if widget is None:
        return
    mark = getattr(widget, "mark_running", None)
    if callable(mark):
        try:
            mark(text=text)
        except TypeError:
            mark()


_mark_subagent_running = mark_subagent_running
_record_subagent_session = record_subagent_session
