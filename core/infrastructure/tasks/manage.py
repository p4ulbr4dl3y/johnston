"""Shared management operations for background shell tasks.

Provides scoping, search, and formatting helpers for ManageShellTool
and TaskManager tasks.
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


def format_tasks_plain(tasks: List[Any]) -> str:
    """Render a canonical plain representation of tasks for LLM consumption."""
    if not tasks:
        return "no active background tasks"

    items = []
    for t in tasks:
        tid = str(getattr(t, "task_id", getattr(t, "id", "")))
        is_running = getattr(t, "is_running", True)
        status = "running" if is_running else "finished"
        cmd = str(getattr(t, "command", ""))
        raw_log = getattr(t, "log_path", None)
        log_part = f" | log: {raw_log}" if raw_log and str(raw_log).strip() else ""
        items.append(f"- ID: {tid} | status: {status} | cmd: {cmd}{log_part}")

    return f"Active Background Tasks ({len(tasks)}):\n" + "\n".join(items)


format_tasks_xml = format_tasks_plain


def not_found_message(task_id: str, tasks: List[Any], manager_name: str) -> str:
    """Build a scoped not-found error with a hint of the active task ids."""
    from core.domain.defaults.errors import format_tool_error

    active_ids = [t.task_id for t in tasks if getattr(t, "is_running", True)]
    if active_ids:
        ids_str = ", ".join(f"'{i}'" for i in active_ids)
        return format_tool_error("notfound", detail=f"active IDs: {ids_str}", name=task_id)
    return format_tool_error("notfound", detail=f"no active {manager_name} tasks", name=task_id)


def find_any(tasks: List[Any], task_id: str) -> Any:
    """Return the first task matching ``task_id`` or None."""
    for t in tasks:
        if getattr(t, "task_id", None) == task_id or getattr(t, "id", None) == task_id:
            return t
    return None
