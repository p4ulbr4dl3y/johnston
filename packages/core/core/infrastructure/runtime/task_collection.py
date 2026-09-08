"""Shared collection of current-session background tasks and subagents.

Both the tasks manager screen and the status footer need the same filtered view
of shell background tasks + subagent sessions for the active session. This
helper keeps that logic in one place.
"""

from dataclasses import dataclass
from typing import Any, List


@dataclass
class TaskCollection:
    """Filtered current-session shell tasks and subagent sessions."""

    shell_tasks: List[Any]
    subagent_tasks: List[Any]


def collect_current_tasks(app, current_session_id: str) -> TaskCollection:
    """Return a :class:`TaskCollection` for the current session.

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
        from core.infrastructure.storage.session_store import SessionStore

        store = SessionStore.get_instance()

    # Fast in-memory resolution to avoid disk signature / listdir on UI ticks
    if hasattr(store, "_sessions") and isinstance(store._sessions, dict):
        all_sess = dict(getattr(store, "_disk_cache", None) or {})
        all_sess.update(store._sessions)
        if current_session_id:
            sessions = [
                s
                for s in all_sess.values()
                if getattr(s, "parent_id", None) == current_session_id
                and getattr(getattr(s, "kind", None), "value", getattr(s, "kind", None)) == "subagent"
            ]
        else:
            sessions = [
                s
                for s in all_sess.values()
                if getattr(getattr(s, "kind", None), "value", getattr(s, "kind", None)) == "subagent"
            ]
    elif current_session_id and hasattr(store, "children"):
        sessions = store.children(current_session_id)
    elif hasattr(store, "list"):
        sessions = store.list(kind="subagent")
    else:
        sessions = []

    return TaskCollection(shell_tasks=bg_tasks, subagent_tasks=sessions)
