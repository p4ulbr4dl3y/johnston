from typing import Any, Optional

from johnston.tui.adapters import core_bridge
from johnston.tui.presentation.tool_display import extract_subagent_progress
from johnston.tui.utils.row_format import MODAL_WIDE_ROW_WIDTH, format_badge_row


def extract_shell_task_progress(task: Any) -> str:
    """Extract a short, human-like activity/status badge for a background shell task."""
    if task is None:
        return ""

    status, dur = core_bridge.extract_task_status_details(task)

    if status == "running":
        return dur if dur and dur != "-" else "running..."

    if status == "killed":
        return "killed"
    if status == "timeout":
        return "timeout"

    if status.startswith("exit:"):
        code = status.split(":", 1)[1]
        dur_suffix = f" • {dur}" if dur and dur != "-" else ""
        return f"exit {code}{dur_suffix}"

    return status or "done"


def format_shell_task_row(
    cmd: str,
    task: Optional[object] = None,
    is_running: bool = False,
    target_width: int = MODAL_WIDE_ROW_WIDTH,
    badge: Optional[str] = None,
) -> str:
    """Format a shell task row with human-like activity/status badge on the right."""
    clean = " ".join(cmd.replace("\n", " ").replace("\r", " ").split()) or "(shell task)"
    if badge is not None:
        badge_plain = badge
    elif task is not None:
        badge_plain = extract_shell_task_progress(task)
    else:
        badge_plain = "running..." if is_running else "done"
    return format_badge_row(clean, badge_plain, target_width=target_width)


def format_subagent_task_row(
    cmd: str,
    session: Optional[object] = None,
    is_running: bool = False,
    target_width: int = MODAL_WIDE_ROW_WIDTH,
    badge: Optional[str] = None,
    role: Optional[str] = None,
) -> str:
    """Format a subagent row with role prefix and human-like activity/status badge on the right."""
    clean = " ".join(cmd.replace("\n", " ").replace("\r", " ").split()) or "(subagent task)"
    if role is not None:
        role_str = role
    elif session is not None:
        agent = getattr(session, "agent", None)
        raw_rn = getattr(agent, "role_name", None) or getattr(session, "role_name", None)
        if isinstance(raw_rn, str) and raw_rn.strip():
            role_str = raw_rn
        else:
            r = getattr(agent, "role", None) if agent else getattr(session, "role", None)
            if isinstance(r, str) and r.strip():
                from johnston.tui.adapters import core_bridge

                role_str = core_bridge.get_role_display_name(r)
            else:
                role_str = "Worker"
    elif ":" in clean.partition(" ")[0]:
        role_str = clean.partition(" ")[0].rstrip(":")
    else:
        role_str = "Worker"

    if not clean.lower().startswith(f"{role_str.lower()}:"):
        clean = f"{role_str}: {clean}"
    else:
        clean = f"{role_str}:{clean[len(role_str)+1:]}"
    if badge is not None:
        badge_plain = badge
    elif session is not None:
        badge_plain = extract_subagent_progress(session)
    else:
        badge_plain = "running..." if is_running else "done"
    return format_badge_row(clean, badge_plain, target_width=target_width)


def _safe_timestamp(val: Any) -> float:
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        try:
            return float(val)
        except Exception:
            pass
    return 0.0


def _filter_and_sort_tasks(items: list, search_query: str) -> list:
    """Apply text search filter and running-first, newest-first ordering to task rows."""
    q = search_query.strip().lower()
    if q:
        items = [it for it in items if q in it["command"].lower() or q in it["id"].lower()]
    return sorted(
        items,
        key=lambda item: (not item.get("is_running", False), -_safe_timestamp(item.get("created_at"))),
    )
