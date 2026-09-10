"""Session facade — thin service layer between TUI and SessionStore/SubagentService.

Absorbs direct SessionStore/SubagentService calls from presentation code.
All functions are core-only (no Textual imports).
"""

import logging
import re
from typing import Any, List, Optional

from johnston.core.domain.entities.session import AgentSession

logger = logging.getLogger(__name__)


def _get_store(app: Any = None) -> Any:
    """Resolve the session store, preferring ``app.sm`` then the singleton."""
    from johnston.core.infrastructure.storage.session_store import SessionStore, get_session_store

    if app is not None:
        return get_session_store(app)
    return SessionStore.get_instance()


# --------------------------------------------------------------------------- #
# Public facade functions
# --------------------------------------------------------------------------- #


def resolve_session_by_title(
    title: str,
    parent_id: Optional[str] = None,
) -> Optional[AgentSession]:
    """Find a session by title or ID, scoped to *parent_id* first then globally.

    Returns the matched session or ``None``.
    """
    if not title:
        return None
    store = _get_store()
    found = store.find_session_by_title_or_id(title, parent_id=parent_id)
    if found is None and parent_id:
        # Fallback: full project-wide search when parent-scoped lookup misses.
        found = store.find_session_by_title_or_id(title)
    return found


def kill_subagent(session: Any, app: Any = None) -> bool:
    """Kill a running subagent session.

    Returns ``True`` on success, ``False`` on failure.
    """
    from johnston.core.application.session.subagent_service import SubagentService

    store = _get_store(app)
    result = SubagentService.kill_subagent(session, store)
    return result is not None and not getattr(result, "is_error", False)


def list_subagent_sessions(
    parent_id: Optional[str] = None,
    app: Any = None,
) -> List[AgentSession]:
    """Return subagent sessions, optionally filtered by *parent_id*."""
    store = _get_store(app)
    if parent_id:
        return store.children(parent_id)
    return store.list(kind="subagent")


_SESSION_ID_RE = re.compile(
    r"(?:\|\s*id\s+|session[_\s-]?id[:=\s]+)([a-zA-Z0-9_-]+)",
    re.IGNORECASE,
)


def resolve_subagent_from_toolcall(
    tool_name: str,
    args: dict,
    app: Any = None,
) -> Optional[str]:
    """Extract a subagent session ID from tool-call arguments.

    Checks explicit ``id`` / ``session_id`` fields first, then attempts a
    regex extraction from ``args["result_text"]`` (or any ``str`` value in
    *args* that looks like a result), and finally falls back to a
    title-based lookup via :func:`resolve_session_by_title`.

    Returns the session-ID string or ``None``.
    """
    if not isinstance(args, dict):
        return None

    # 1. Explicit ID fields.
    session_id: Optional[str] = args.get("id") or args.get("session_id")
    if session_id:
        return str(session_id)

    # 2. Regex extraction from result_text / any str values in args.
    text_to_scan = args.get("result_text", "") or ""
    if not text_to_scan:
        for v in args.values():
            if isinstance(v, str) and ("id" in v.lower() or "session" in v.lower()):
                text_to_scan = v
                break
    if text_to_scan:
        m = _SESSION_ID_RE.search(str(text_to_scan))
        if m:
            return m.group(1)

    # 3. Title-based lookup (invoke_subagent / message_subagent).
    if tool_name in ("invoke_subagent", "message_subagent"):
        title = args.get("title") or args.get("prompt")
        if title:
            app_ref = app
            curr_sid = getattr(app_ref, "current_session_id", None) if app_ref else None
            sess = resolve_session_by_title(str(title), parent_id=curr_sid)
            if sess is not None and isinstance(getattr(sess, "id", None), str):
                return sess.id

    return None
