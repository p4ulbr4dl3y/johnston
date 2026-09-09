"""Session JSONL serialization and file I/O for AgentSession.

Persistence extracted from the former god object
``core/domain/entities/session.py`` so the entity stays a plain domain
record. On-disk format is unchanged: JSONL with ``_type: meta/msg/history``
lines and the exact scalar key set from ``persistent_fields``.
"""
import json
import os
from typing import Any, Dict, List, Optional

from johnston.core.domain.entities.session import (
    AgentSession,
    MessageType,
    SessionKind,
    SessionStatus,
    _coerce_float,
    _coerce_int,
    sanitize_session_event,
)

_META_TYPE = "meta"
_MSG_TYPE = "msg"
_HISTORY_TYPE = "history"


def persistent_fields(sess: AgentSession) -> Dict[str, Any]:
    """Scalar (non-message) fields shared by to_dict and to_jsonl_lines meta."""
    return {
        "id": sess.id,
        "kind": sess.kind.value,
        "parent_id": sess.parent_id,
        "role": sess.role,
        "status": sess.status,
        "project_key": sess.project_key,
        "title": sess._title,
        "prompt": sess.prompt,
        "auto_titled": sess.auto_titled,
        "fork_msg_count": sess.fork_msg_count,
        "tokens_input": sess.tokens_input,
        "tokens_output": sess.tokens_output,
        "total_tokens": sess.total_tokens,
        "cost_usd": sess.cost_usd,
        "last_context_tokens": sess.last_context_tokens,
        "tokens_cache_read": sess.tokens_cache_read,
        "created_at": sess.created_at,
        "updated_at": sess.updated_at,
        "project_dir": sess.project_dir,
        "branch_name": sess.branch_name,
    }


def session_history(sess: AgentSession) -> List[Dict[str, Any]]:
    """Agent history: prefer the live agent's history, fall back to the stored copy."""
    history = getattr(sess.agent, "history", None)
    return history if history is not None else sess.agent_history


def to_dict(sess: AgentSession) -> Dict[str, Any]:
    data = persistent_fields(sess)
    data["messages"] = sess.messages
    data["agent_history"] = session_history(sess)
    return data


def to_jsonl_lines(sess: AgentSession) -> List[Dict[str, Any]]:
    meta = {"_type": _META_TYPE, **persistent_fields(sess)}
    lines: List[Dict[str, Any]] = [meta]
    for m in sess.messages:
        lines.append({"_type": _MSG_TYPE, "data": sanitize_session_event(m) if isinstance(m, dict) else str(m)})
    for h in session_history(sess):
        lines.append({"_type": _HISTORY_TYPE, "data": sanitize_session_event(h) if isinstance(h, dict) else str(h)})
    return lines


def from_dict(data: Dict[str, Any]) -> AgentSession:
    raw_kind = data.get("kind", SessionKind.MAIN.value)
    try:
        kind = SessionKind(raw_kind)
    except ValueError:
        kind = SessionKind.MAIN
    sess = AgentSession(
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


def from_file(fpath: str) -> Optional[AgentSession]:
    """Load a session from the on-disk JSONL format; None on missing/corrupt input."""
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

            if not isinstance(first, dict) or first.get("_type") != _META_TYPE:
                return None

            sess = from_dict(first)
            sess._loaded_from_disk = True
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
                if etype == _MSG_TYPE:
                    data = entry.get("data")
                    sess.messages.append(data if data is not None else {})
                elif etype == _HISTORY_TYPE:
                    data = entry.get("data")
                    sess.agent_history.append(data if data is not None else {})
            reconcile_compaction_divider(sess)
            return sess
    except Exception:
        return None


def reconcile_compaction_divider(sess: AgentSession) -> None:
    """Ensure sessions with compaction checkpoints have at least one visible event divider."""
    if not sess.agent_history or any(
        isinstance(m, dict) and m.get("type") == MessageType.EVENT_DIVIDER
        for m in sess.messages
    ):
        return
    for h in sess.agent_history:
        if isinstance(h, dict) and isinstance(h.get("content"), str) and h["content"].startswith("<compaction_checkpoint>"):
            sess.messages.append({"type": MessageType.EVENT_DIVIDER, "text": "Session Compacted"})
            break
