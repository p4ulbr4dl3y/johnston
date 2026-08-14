"""Shared management operations for shell and subagent tasks.

Both ManageShellTool and ManageSubagentTool used to duplicate the same
scoping/status/kill logic. This module centralizes that logic behind a small
surface that each tool delegates to, so behaviour stays consistent and the
duplication is removed.
"""

from typing import Any, List


def filter_to_session(tasks: List[Any], current_session_id: str) -> List[Any]:
    """Return only tasks belonging to the active session.

    Matches the tasks screen and status footer: when a session is active, only
    tasks carrying that ``session_id`` are considered; otherwise all are used.
    """
    if isinstance(current_session_id, str) and current_session_id:
        return [t for t in tasks if getattr(t, "session_id", None) == current_session_id]
    return list(tasks)


def list_lines(tasks: List[Any], *, header: str = "Active Background Tasks:") -> str:
    """Render a canonical list of tasks with status and command."""
    if not tasks:
        return "no tasks active"
    lines = [header]
    for t in tasks:
        status = "RUNNING" if getattr(t, "is_running", True) else "FINISHED"
        lines.append(f"- ID: {t.task_id} | Status: {status} | Command: {t.command}")
    return "\n".join(lines)


def not_found_message(task_id: str, tasks: List[Any], manager_name: str) -> str:
    """Build a scoped not-found error with a hint of the active task ids."""
    from tools.base import format_tool_error

    active_ids = [t.task_id for t in tasks if getattr(t, "is_running", True)]
    if active_ids:
        ids_str = ", ".join(f"'{i}'" for i in active_ids)
        return format_tool_error("notfound", detail=f"[Hint: Active IDs: {ids_str}]", name=task_id)
    return format_tool_error("notfound", detail=f"[Hint: No active {manager_name} tasks]", name=task_id)


def find_any(tasks: List[Any], task_id: str) -> Any:
    """Return the first task matching ``task_id`` or None."""
    for t in tasks:
        if getattr(t, "task_id", None) == task_id or getattr(t, "id", None) == task_id:
            return t
    return None
