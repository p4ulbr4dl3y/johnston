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
        from core.session_manager import SessionStore

        store = SessionStore.get_instance()
    sessions = store.children(current_session_id) if current_session_id else store.list(kind="subagent")
    return TaskCollection(shell_tasks=bg_tasks, subagent_tasks=sessions)
