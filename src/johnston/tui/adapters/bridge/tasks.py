"""Task and subagent bridge adapters between TUI and core."""
from __future__ import annotations

from typing import Any, Optional

from johnston.core.infrastructure.tasks.output import (
    is_spinner_line,
    process_carriage_returns,
    process_carriage_returns_lines,
    strip_ansi,
)

__all__ = [
    "collect_current_tasks",
    "collect_task_summary",
    "extract_task_status_details",
    "filter_to_session",
    "format_duration",
    "get_extract_task_status_details",
    "is_spinner_line",
    "kill_subagent",
    "process_carriage_returns",
    "process_carriage_returns_lines",
    "strip_ansi",
]


def collect_task_summary(
    app: Any, session_id: Optional[str] = None
) -> tuple[list[Any], list[Any]]:
    """Return (shell_tasks, subagent_sessions) for the current app/session."""
    from johnston.core.infrastructure.runtime.task_collection import (
        collect_current_tasks as _collect,
    )

    tasks = _collect(app, session_id)
    return tasks.shell_tasks, tasks.subagent_tasks


def collect_current_tasks(app: Any, session_id: Optional[str] = None) -> Any:
    """Collect shell/subagent task state for the status footer (core helper)."""
    from johnston.core.infrastructure.runtime.task_collection import (
        collect_current_tasks as _f,
    )

    return _f(app, session_id)


def filter_to_session(tasks: Any, session_id: Any) -> Any:
    """Filter tasks to the given session scope (core task manager helper)."""
    from johnston.core.infrastructure.tasks.manage import (
        filter_to_session as _f,
    )

    return _f(tasks, session_id)


def format_duration(seconds: float | int | None) -> str:
    """Format a duration as a concise string (core task helper)."""
    from johnston.core.infrastructure.tasks.manage import format_duration as _f

    return _f(seconds)


def kill_subagent(session: Any, app: Any = None) -> bool:
    """Kill a subagent session (core client facade)."""
    from johnston.core.client import kill_subagent as _f

    return _f(session, app)


def extract_task_status_details(task: Any) -> tuple[str, str]:
    """Task status + badge from a core task object."""
    from johnston.core.client import extract_task_status_details as _e

    return _e(task)


def get_extract_task_status_details() -> Any:
    """Core task status extraction helper."""
    from johnston.core.client import extract_task_status_details as _f

    return _f
