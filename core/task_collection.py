"""Shared collection of current-session background tasks and subagents.

Both the tasks manager screen and the status footer need the same filtered view
of shell background tasks + subagent sessions for the active session. This
helper keeps that logic in one place.
"""

from typing import Any, List, Tuple


def collect_current_tasks(app, current_session_id: str) -> Tuple[List[Any], List[Any]]:
    """Return (shell tasks, subagent sessions) for the current session.

    Shell tasks come from the app's TaskManager and are filtered by
    ``session_id`` when a session is active, otherwise all are returned.
    Subagents are resolved via the session store.
    """
    mgr = getattr(app, "task_manager", None) if app else None
    if mgr is not None:
        bg_tasks = [t for t in mgr if getattr(t, "kind", "") == "shell"]
    else:
        bg_tasks = []
    if current_session_id:
        bg_tasks = [t for t in bg_tasks if getattr(t, "session_id", None) == current_session_id]

    store = getattr(app, "sm", None) if app else None
    if store is None:
        from core.session_manager import SessionStore

        store = SessionStore.get_instance()
    sessions = (
        store.get_subagents_for_parent(current_session_id)
        if current_session_id
        else store.list(kind="subagent")
    )
    return bg_tasks, sessions
