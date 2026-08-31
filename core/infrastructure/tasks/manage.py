"""Shared management operations for background shell tasks.

Provides scoping, search, and formatting helpers for ManageShellTool
and TaskManager tasks.
"""

import time
from typing import Any, List


def filter_to_session(tasks: List[Any], current_session_id: str) -> List[Any]:
    """Return only tasks belonging to the active session.

    Matches the tasks screen and status footer: when a session is active, only
    tasks carrying that ``session_id`` are considered; otherwise all are used.
    """
    if isinstance(current_session_id, str) and current_session_id:
        return [t for t in tasks if getattr(t, "session_id", None) == current_session_id]
    return list(tasks)


def format_duration(seconds: float | int | None) -> str:
    """Format duration in seconds as concise string ('<0.1s', '4.2s', '14s', '1m 20s', '2h 15m')."""
    if seconds is None:
        return ""
    try:
        sec = float(seconds)
    except (ValueError, TypeError):
        return ""
    if sec < 0:
        sec = 0.0
    if sec < 60:
        if sec < 0.1:
            return "<0.1s" if sec > 0 else "0s"
        if sec < 10:
            return f"{sec:.1f}s"
        return f"{int(sec)}s"
    if sec < 3600:
        minutes = int(sec // 60)
        secs = int(sec % 60)
        return f"{minutes}m {secs:02d}s"
    hours = int(sec // 3600)
    mins = int((sec % 3600) // 60)
    return f"{hours}h {mins:02d}m"


def extract_task_status_details(task: Any) -> tuple[str, str]:
    """Extract canonical (status, duration) details for a task."""
    if task is None:
        return "finished", "-"

    is_running = bool(getattr(task, "is_running", False))
    now = time.time()
    created_at = getattr(task, "created_at", None)
    completed_at = getattr(task, "completed_at", None)

    dur_str = "-"
    if isinstance(created_at, (int, float)) and not isinstance(created_at, bool) and created_at > 0:
        if is_running:
            dur_str = format_duration(max(0.0, now - created_at)) or "-"
        elif isinstance(completed_at, (int, float)) and not isinstance(completed_at, bool) and completed_at > 0:
            dur_str = format_duration(max(0.0, completed_at - created_at)) or "-"

    if is_running:
        return "running", dur_str

    st_raw = getattr(task, "status", None)
    st_str = ""
    if isinstance(st_raw, str):
        st_str = st_raw.lower()
    elif hasattr(st_raw, "value") and isinstance(getattr(st_raw, "value", None), str):
        st_str = st_raw.value.lower()

    was_killed = bool(getattr(task, "was_killed", False)) or st_str == "killed"
    if was_killed:
        return "killed", dur_str
    if st_str == "timeout":
        return "timeout", dur_str

    exit_code = getattr(task, "exit_code", None)
    if exit_code is None and getattr(task, "process", None) is not None:
        exit_code = getattr(task.process, "returncode", None)

    if isinstance(exit_code, int) and not isinstance(exit_code, bool):
        return f"exit:{exit_code}", dur_str

    if st_str in ("completed", "finished", "done"):
        return "exit:0", dur_str
    if st_str == "error":
        return "exit:1", dur_str

    return st_str if st_str in ("running", "finished", "completed", "done", "error", "killed", "timeout") else "finished", dur_str


def list_lines(tasks: List[Any], *, header: str = "Active Background Tasks:") -> str:
    """Render a canonical list of tasks with status and command."""
    if not tasks:
        return "no tasks active"
    lines = [header]
    for t in tasks:
        status, dur = extract_task_status_details(t)
        st_display = status.upper()
        if dur and dur != "-":
            st_display = f"{st_display} ({dur})"
        lines.append(f"- ID: {t.task_id} | Status: {st_display} | Command: {t.command}")
    return "\n".join(lines)


def format_tasks_plain(tasks: List[Any]) -> str:
    """Render a canonical plain representation of tasks for LLM consumption."""
    if not tasks:
        return "[tasks 0]"

    items = []
    for t in tasks:
        tid = str(getattr(t, "task_id", ""))
        status, dur = extract_task_status_details(t)
        cmd = str(getattr(t, "command", ""))
        raw_log = str(getattr(t, "log_path", "") or "").strip()
        items.append(f"{tid}|{status}|{dur}|{cmd}|{raw_log}")

    return f"[tasks {len(tasks)} | id|status|duration|cmd|log]\n" + "\n".join(items)


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
        if getattr(t, "task_id", None) == task_id:
            return t
    return None
