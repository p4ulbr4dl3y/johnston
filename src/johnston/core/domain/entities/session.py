import time
from enum import Enum
from typing import Any, Dict, List, Optional


class SessionStatus(str, Enum):
    """Canonical session lifecycle statuses.

    ``str, Enum`` so the persisted/rendered value is the plain string
    (``.value``) and comparisons against ``str`` literals keep working.
    """

    ACTIVE = "active"
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"

    def __str__(self) -> str:
        return self.value


class SessionKind(str, Enum):
    """Type of an AgentSession record: a main chat session or a subagent task."""

    MAIN = "main"
    SUBAGENT = "subagent"


class MessageType(str, Enum):
    """Canonical event/message types stored in session.messages.

    Persisted as plain strings (``.value``) so on-disk JSON stays compatible.
    Raw inbound events are dicts with a ``"type"`` field; enum values are used
    at construction/coalescing boundaries.
    """

    BOT = "bot"
    BOT_RESET = "bot_reset"
    THINKING = "thinking"
    TOOL = "tool"
    TOOL_GENERATING = "tool_generating"
    TOOL_GENERATING_UPDATE = "tool_generating_update"
    TOOL_SHELL_OUTPUT = "tool_shell_output"
    STATUS_CHANGE = "status_change"
    EVENT_DIVIDER = "event_divider"
    ERROR = "error"


def _coerce_int(val: Any) -> int:
    """Coerce a persisted token count to int, tolerating None/invalid types."""
    if val is None or isinstance(val, bool):
        return 0
    try:
        return int(val)
    except (ValueError, TypeError):
        return 0


def _coerce_float(val: Any) -> float:
    """Coerce a persisted cost value to float, tolerating None/invalid types."""
    if val is None or isinstance(val, bool):
        return 0.0
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


def _now() -> float:
    return time.time()


def sanitize_session_event(obj: Any, depth: int = 0, seen: Optional[set] = None) -> Any:
    """Sanitize event payload recursively to guarantee JSON serializability."""
    if obj is None or isinstance(obj, (str, int, float, bool)):
        return obj
    if depth > 50:
        return str(obj)
    if isinstance(obj, BaseException):
        return str(obj)
    if seen is None:
        seen = set()
    obj_id = id(obj)
    if obj_id in seen:
        return "<circular>"
    seen.add(obj_id)
    try:
        if isinstance(obj, dict):
            return {str(k): sanitize_session_event(v, depth + 1, seen) for k, v in obj.items()}
        if isinstance(obj, (list, tuple, set)):
            return [sanitize_session_event(x, depth + 1, seen) for x in obj]
        return str(obj)
    finally:
        seen.remove(obj_id)


class AgentSession:
    """Unified session model for main chat sessions and subagent task sessions.

    Hierarchy: project -> main session -> subagent sessions (parent_id).
    Messages use a single renderable format shared with the chat UI.

    Pure domain record: live streaming/coalescing lives in
    ``johnston.core.infrastructure.runtime.session_coalescer``, persistence in
    ``johnston.core.infrastructure.storage.session_serialization`` and interruption/
    compaction finalization in
    ``johnston.core.infrastructure.runtime.session_interruption``; this class only
    holds state and thin delegating methods.
    """

    def __init__(
        self,
        session_id: str,
        kind: SessionKind = SessionKind.MAIN,
        parent_id: Optional[str] = None,
        role: str = "worker",
        status: str = SessionStatus.ACTIVE,
        project_key: str = "",
        title: str = "",
        prompt: str = "",
        created_at: Optional[float] = None,
        updated_at: Optional[float] = None,
        auto_titled: bool = False,
        fork_msg_count: int = 0,
    ):
        self.id = session_id
        self.kind = kind
        self.parent_id = parent_id
        self.role = role
        self._role_name: Optional[str] = None
        self.status = status
        self.project_key = project_key
        self._title = title
        self.prompt = prompt
        self.auto_titled = auto_titled
        self.fork_msg_count = fork_msg_count
        self.messages: List[Dict[str, Any]] = []
        self.agent_history: List[Dict[str, Any]] = []
        self.tokens_input: int = 0
        self.tokens_output: int = 0
        self.total_tokens: int = 0
        self.cost_usd: float = 0.0
        self.last_context_tokens: int = 0
        self.tokens_cache_read: int = 0
        self.created_at = created_at or _now()
        self.updated_at = updated_at or self.created_at

        # Live-state only (never persisted): streaming agent, listeners, async task.
        self.agent: Any = None
        self.listeners: List[Any] = []
        self.async_task: Any = None
        self.pending_messages: List[Any] = []  # follow-up queue (live, not persisted)
        self._next_unmatched_tool_idx: int = 0  # first index with a possibly-unmatched TOOL msg (live)
        self.project_dir: str = ""
        self.branch_name: str = ""
        self.background: bool = True

    @property
    def role_name(self) -> str:
        if getattr(self, "_role_name", None):
            return self._role_name
        from johnston.core.application.roles.role_registry import resolve_role_display_name

        return resolve_role_display_name(self.role, project_dir=self.project_dir or None)

    @role_name.setter
    def role_name(self, value: str) -> None:
        self._role_name = value

    @property
    def plan(self) -> Optional[List[Dict[str, Any]]]:
        if getattr(self, "_plan", None) is not None:
            return self._plan
        if getattr(self, "current_plan", None) is not None:
            return self.current_plan
        if getattr(self, "messages", None):
            try:
                from johnston.core.application.session.rewind import restore_plan_from_messages

                p, _ = restore_plan_from_messages(self.messages)
                if p:
                    self._plan = p
                    return p
            except Exception:
                pass
        return None

    @plan.setter
    def plan(self, value: Optional[List[Dict[str, Any]]]) -> None:
        self._plan = value
        self.current_plan = value

    # -- live event streaming (delegated to session_coalescer) -------------

    def add_event(self, event: Dict[str, Any]) -> None:
        """Append a stream event, coalescing consecutive chunks into canonical messages."""
        from johnston.core.infrastructure.runtime.session_coalescer import add_event

        add_event(self, event)

    def add_listener(self, cb: Any) -> None:
        from johnston.core.infrastructure.runtime.session_coalescer import add_listener

        add_listener(self, cb)

    def remove_listener(self, cb: Any) -> None:
        from johnston.core.infrastructure.runtime.session_coalescer import remove_listener

        remove_listener(self, cb)

    def touch(self) -> None:
        self.updated_at = _now()

    def finish(self, status: str, error_msg: str = "") -> None:
        self.status = status
        self.add_event({
            "type": MessageType.STATUS_CHANGE.value,
            "status": status,
            "error": str(error_msg) if error_msg else "",
        })

    def record_interruption(self, divider_text: str = "Response Interrupted") -> None:
        """Finalize any in-flight tool or thinking events and append an interruption divider."""
        from johnston.core.infrastructure.runtime.session_interruption import record_session_interruption

        record_session_interruption(self, divider_text)

    def record_compaction(self, title: str = "Session Compacted") -> None:
        """Record compaction event divider into session messages."""
        self.add_event({"type": MessageType.EVENT_DIVIDER.value, "text": title})

    # -- persistence (delegated to session_serialization) ------------------

    def _history(self) -> List[Dict[str, Any]]:
        """Agent history: prefer the live agent's history, fall back to the stored copy."""
        from johnston.core.infrastructure.storage.session_serialization import session_history

        return session_history(self)

    def _persistent_fields(self) -> Dict[str, Any]:
        """Scalar (non-message) fields shared by to_dict and to_jsonl_lines meta."""
        from johnston.core.infrastructure.storage.session_serialization import persistent_fields

        return persistent_fields(self)

    def to_dict(self) -> Dict[str, Any]:
        from johnston.core.infrastructure.storage.session_serialization import to_dict

        return to_dict(self)

    def to_jsonl_lines(self) -> List[Dict[str, Any]]:
        from johnston.core.infrastructure.storage.session_serialization import to_jsonl_lines

        return to_jsonl_lines(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentSession":
        from johnston.core.infrastructure.storage.session_serialization import from_dict

        return from_dict(data)

    def reconcile_compaction_divider(self) -> None:
        """Ensure sessions with compaction checkpoints have at least one visible event divider."""
        from johnston.core.infrastructure.storage.session_serialization import (
            reconcile_compaction_divider,
        )

        reconcile_compaction_divider(self)

    @property
    def title(self) -> str:
        if self._title:
            clean = " ".join(str(self._title).split())
            if clean:
                return clean
        from johnston.core.domain.policies.messages import is_ui_visible_user_message

        for m in self.messages:
            if isinstance(m, dict) and is_ui_visible_user_message(m):
                text = str(m.get("display_text") or m.get("text", "")).strip()
                if text:
                    clean = " ".join(text.split())
                    return clean
        return "Untitled"

    @title.setter
    def title(self, value: str) -> None:
        self._title = str(value) if value is not None else ""

    @property
    def turn_count(self) -> int:
        """Count agent loop iterations / turns (bot responses and tool calls) across full session history."""
        if self.messages:
            agent_msgs = [
                m
                for m in self.messages
                if isinstance(m, dict)
                and (m.get("type") == "bot" or (m.get("type") == "tool" and m.get("tool_type")))
            ]
            if agent_msgs:
                return len(agent_msgs)
        if self.agent_history:
            assistant_msgs = [m for m in self.agent_history if isinstance(m, dict) and m.get("role") == "assistant"]
            if assistant_msgs:
                return len(assistant_msgs)
        return 0

    @property
    def message_count(self) -> int:
        """Count assistant iterations in history or UI messages."""
        return self.turn_count

    def to_summary_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "parent_id": self.parent_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": self.message_count,
            "turn_count": self.turn_count,
        }

    @classmethod
    def from_file(cls, fpath: str) -> Optional["AgentSession"]:
        from johnston.core.infrastructure.storage.session_serialization import from_file

        return from_file(fpath)


def record_session_interruption(session: Any, divider_text: str = "Response Interrupted") -> None:
    """Unify cancellation/interruption finalization across main agent and subagents."""
    from johnston.core.infrastructure.runtime.session_interruption import (
        record_session_interruption as _record,
    )

    _record(session, divider_text)


def record_session_compaction(session: Any, title: str = "Session Compacted") -> None:
    """Unify compaction divider recording across session instances."""
    from johnston.core.infrastructure.runtime.session_interruption import (
        record_session_compaction as _record,
    )

    _record(session, title)
