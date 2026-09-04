import json
import logging
import os
import time
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


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


class AgentSession:
    """Unified session model for main chat sessions and subagent task sessions.

    Hierarchy: project -> main session -> subagent sessions (parent_id).
    Messages use a single renderable format shared with the chat UI.
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
        from core.role_registry import resolve_role_display_name

        return resolve_role_display_name(self.role, project_dir=self.project_dir or None)

    @role_name.setter
    def role_name(self, value: str) -> None:
        self._role_name = value

    # -- live event streaming (subagents) ---------------------------------

    def add_event(self, event: Dict[str, Any]) -> None:
        """Append a stream event, coalescing consecutive chunks into canonical messages.

        Canonical message types (shared with main session snapshots):
        - "bot": text of a reply, coalesced (replace) across stream chunks
        - "thinking": text + optional duration, coalesced until thinking finishes
        - "tool": tool call, with "result_text" merged into the same message
        """
        etype = event.get("type", "")
        last = self.messages[-1] if self.messages else None

        if etype == MessageType.BOT and last and last.get("type") == MessageType.BOT:
            last["text"] = event.get("text", "")
            last.pop("delta", None)
            if event.get("final"):
                last["final"] = True
        elif etype == MessageType.BOT_RESET and last and last.get("type") == MessageType.BOT:
            last["text"] = ""
            last.pop("final", None)
            last.pop("delta", None)
        elif etype == MessageType.THINKING and last and last.get("type") == MessageType.THINKING and "duration" not in last:
            last["text"] = event.get("text", "")
            if event.get("duration") is not None:
                last["duration"] = event["duration"]
            last.pop("phase", None)
        elif etype == MessageType.TOOL and "result_text" in event:
            target_msg = None
            # Tool results always land on the FIRST unmatched TOOL message (no
            # tool-id correlation upstream), so everything before the pointer is
            # already matched or non-matchable and must not be rescanned: O(1)
            # amortized per result. Clamp on truncation/rewind, which may replace
            # self.messages with a shorter prefix (re-exposed messages keep their
            # result_text, so skipping them matches the old from-0 scan).
            idx = min(self._next_unmatched_tool_idx, len(self.messages))
            for i in range(idx, len(self.messages)):
                msg = self.messages[i]
                if isinstance(msg, dict) and msg.get("type") == MessageType.TOOL and "result_text" not in msg:
                    target_msg = msg
                    self._next_unmatched_tool_idx = i + 1
                    break
            else:
                self._next_unmatched_tool_idx = len(self.messages)
            if target_msg is not None:
                target_msg["result_text"] = event["result_text"]
                for key in ("status", "is_error", "returncode"):
                    if key in event:
                        target_msg[key] = event[key]
            else:
                msg_to_store = dict(event)
                msg_to_store.pop("phase", None)
                msg_to_store.pop("delta", None)
                msg_to_store.pop("from_stream_step", None)
                self.messages.append(msg_to_store)
                self.updated_at = _now()
        elif (
            etype == MessageType.EVENT_DIVIDER
            and last
            and last.get("type") == MessageType.EVENT_DIVIDER
            and last.get("text") == event.get("text")
        ):
            return
        else:
            if etype == MessageType.TOOL and last and last.get("type") == MessageType.BOT and not last.get("text", "").strip():
                self.messages.pop()
            msg_to_store = dict(event)
            msg_to_store.pop("phase", None)
            msg_to_store.pop("delta", None)
            msg_to_store.pop("from_stream_step", None)
            self.messages.append(msg_to_store)
            self.updated_at = _now()

        if not self.listeners:
            return
        for cb in list(self.listeners):
            try:
                cb(event)
            except Exception:
                logger.warning("Session listener callback failed", exc_info=True)

    def add_listener(self, cb: Any) -> None:
        if cb not in self.listeners:
            self.listeners.append(cb)

    def remove_listener(self, cb: Any) -> None:
        if cb in self.listeners:
            self.listeners.remove(cb)

    def touch(self) -> None:
        self.updated_at = _now()

    def finish(self, status: str, error_msg: str = "") -> None:
        self.status = status
        self.add_event({"type": MessageType.STATUS_CHANGE.value, "status": status, "error": error_msg})

    def record_interruption(self, divider_text: str = "Response Interrupted") -> None:
        """Finalize any in-flight tool or thinking events and append an interruption divider."""
        if self.messages:
            for msg in reversed(self.messages):
                if isinstance(msg, dict):
                    if msg.get("type") == MessageType.TOOL.value and "result_text" not in msg:
                        self.add_event({
                            "type": MessageType.TOOL.value,
                            "result_text": "[interrupted | tool cancelled]",
                            "status": "cancelled",
                        })
                    elif msg.get("type") == MessageType.THINKING.value and "duration" not in msg:
                        self.add_event({
                            "type": MessageType.THINKING.value,
                            "duration": 0.0,
                        })
                    else:
                        break
        try:
            self.add_event({"type": MessageType.EVENT_DIVIDER.value, "text": divider_text})
        except Exception:
            pass


    # -- persistence -------------------------------------------------------

    def _history(self) -> List[Dict[str, Any]]:
        """Agent history: prefer the live agent's history, fall back to the stored copy."""
        history = getattr(self.agent, "history", None)
        return history if history is not None else self.agent_history

    def _persistent_fields(self) -> Dict[str, Any]:
        """Scalar (non-message) fields shared by to_dict and to_jsonl_lines meta."""
        return {
            "id": self.id,
            "kind": self.kind.value,
            "parent_id": self.parent_id,
            "role": self.role,
            "status": self.status,
            "project_key": self.project_key,
            "title": self._title,
            "prompt": self.prompt,
            "auto_titled": self.auto_titled,
            "fork_msg_count": self.fork_msg_count,
            "tokens_input": self.tokens_input,
            "tokens_output": self.tokens_output,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "last_context_tokens": self.last_context_tokens,
            "tokens_cache_read": self.tokens_cache_read,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "project_dir": self.project_dir,
            "branch_name": self.branch_name,
        }

    def to_dict(self) -> Dict[str, Any]:
        data = self._persistent_fields()
        data["messages"] = self.messages
        data["agent_history"] = self._history()
        return data

    def to_jsonl_lines(self) -> List[Dict[str, Any]]:
        meta = {"_type": "meta", **self._persistent_fields()}
        lines: List[Dict[str, Any]] = [meta]
        for m in self.messages:
            lines.append({"_type": "msg", "data": m})
        for h in self._history():
            lines.append({"_type": "history", "data": h})
        return lines

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentSession":
        raw_kind = data.get("kind", SessionKind.MAIN.value)
        try:
            kind = SessionKind(raw_kind)
        except ValueError:
            kind = SessionKind.MAIN
        sess = cls(
            session_id=data.get("id", ""),
            kind=kind,
            parent_id=data.get("parent_id"),
            role=data.get("role", "worker"),
            status=data.get("status", SessionStatus.ACTIVE),
            project_key=data.get("project_key", ""),
            title=data.get("title") or "",
            prompt=data.get("prompt") or "",
            created_at=data.get("created_at"),
            updated_at=data.get("updated_at"),
            auto_titled=bool(data.get("auto_titled", False)),
            fork_msg_count=_coerce_int(data.get("fork_msg_count")),
        )
        sess.messages = data.get("messages", [])
        sess.agent_history = data.get("agent_history", [])
        sess.tokens_input = _coerce_int(data.get("tokens_input"))
        sess.tokens_output = _coerce_int(data.get("tokens_output"))
        sess.total_tokens = _coerce_int(data.get("total_tokens"))
        sess.cost_usd = _coerce_float(data.get("cost_usd"))
        sess.last_context_tokens = _coerce_int(data.get("last_context_tokens"))
        sess.tokens_cache_read = _coerce_int(data.get("tokens_cache_read"))
        sess.project_dir = data.get("project_dir", "")
        sess.branch_name = data.get("branch_name", "")
        return sess

    @property
    def title(self) -> str:
        if self._title:
            clean = " ".join(str(self._title).split())
            if clean:
                return clean
        for m in self.messages:
            if isinstance(m, dict) and m.get("type") == "user":
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
        if not fpath or not os.path.exists(fpath):
            return None
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                first_line = f.readline().strip()
                if not first_line:
                    return None
                try:
                    first = json.loads(first_line)
                except Exception:
                    return None

                if not isinstance(first, dict) or first.get("_type") != "meta":
                    return None

                sess = cls.from_dict(first)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entry = json.loads(line)
                    except Exception:
                        continue
                    if not isinstance(entry, dict):
                        continue
                    etype = entry.get("_type")
                    if etype == "msg":
                        data = entry.get("data")
                        sess.messages.append(data if data is not None else {})
                    elif etype == "history":
                        data = entry.get("data")
                        sess.agent_history.append(data if data is not None else {})
                return sess
        except Exception:
            return None


def record_session_interruption(session: Any, divider_text: str = "Response Interrupted") -> None:
    """Unify cancellation/interruption finalization across main agent and subagents."""
    if not session:
        return
    if isinstance(session, AgentSession):
        session.record_interruption(divider_text)
        return
    if hasattr(session, "messages") and session.messages:
        for msg in reversed(session.messages):
            if isinstance(msg, dict):
                if msg.get("type") == MessageType.TOOL.value and "result_text" not in msg:
                    try:
                        session.add_event({
                            "type": MessageType.TOOL.value,
                            "result_text": "[interrupted | tool cancelled]",
                            "status": "cancelled",
                        })
                    except Exception:
                        pass
                elif msg.get("type") == MessageType.THINKING.value and "duration" not in msg:
                    try:
                        session.add_event({
                            "type": MessageType.THINKING.value,
                            "duration": 0.0,
                        })
                    except Exception:
                        pass
                else:
                    break
    if hasattr(session, "add_event"):
        try:
            session.add_event({"type": MessageType.EVENT_DIVIDER.value, "text": divider_text})
        except Exception:
            pass

