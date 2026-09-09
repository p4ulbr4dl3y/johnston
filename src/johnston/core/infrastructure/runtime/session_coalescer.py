"""Live session event coalescing and listener dispatch for AgentSession.

Streaming state machine extracted from the former god object
``core/domain/entities/session.py`` (``AgentSession.add_event``): it mutates
the session's live state directly (``messages``, ``updated_at``,
``_next_unmatched_tool_idx``, ``listeners``) so the entity stays a plain
domain record. Shared by main-chat and subagent streaming.
"""
import logging
from typing import Any, Dict

from johnston.core.domain.entities.session import MessageType, sanitize_session_event

logger = logging.getLogger(__name__)


def add_event(session: Any, event: Dict[str, Any]) -> None:
    """Append a stream event, coalescing consecutive chunks into canonical messages.

    Canonical message types (shared with main session snapshots):
    - "bot": text of a reply, coalesced (replace) across stream chunks
    - "thinking": text + optional duration, coalesced until thinking finishes
    - "tool": tool call, with "result_text" merged into the same message
    """
    etype = event.get("type", "")
    event = sanitize_session_event(event)
    last = session.messages[-1] if session.messages else None

    if etype in (
        MessageType.TOOL_GENERATING,
        MessageType.TOOL_GENERATING_UPDATE,
        MessageType.TOOL_SHELL_OUTPUT,
        "tool_generating",
        "tool_generating_update",
        "tool_shell_output",
    ):
        if not session.listeners:
            return
        _notify_listeners(session, event)
        return

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
        if event.get("phase") == "delta":
            last["text"] = (last.get("text", "") or "") + (event.get("text", "") or "")
        else:
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
        # session.messages with a shorter prefix (re-exposed messages keep their
        # result_text, so skipping them matches the old from-0 scan).
        idx = min(session._next_unmatched_tool_idx, len(session.messages))
        for i in range(idx, len(session.messages)):
            msg = session.messages[i]
            if isinstance(msg, dict) and msg.get("type") == MessageType.TOOL and "result_text" not in msg:
                target_msg = msg
                session._next_unmatched_tool_idx = i + 1
                break
        else:
            session._next_unmatched_tool_idx = len(session.messages)
        if target_msg is not None:
            target_msg["result_text"] = event["result_text"]
            for key in ("status", "is_error", "returncode", "task_id", "background_task_id", "subagent_session_id", "log_path"):
                if key in event:
                    target_msg[key] = event[key]
            if event.get("tool_id"):
                target_msg["tool_call_id"] = event["tool_id"]
        else:
            msg_to_store = dict(event)
            msg_to_store.pop("phase", None)
            msg_to_store.pop("delta", None)
            msg_to_store.pop("from_stream_step", None)
            session.messages.append(msg_to_store)
            session.updated_at = _now()
    elif (
        etype == MessageType.EVENT_DIVIDER
        and last
        and last.get("type") == MessageType.EVENT_DIVIDER
        and last.get("text") == event.get("text")
    ):
        return
    else:
        if etype == MessageType.TOOL and last and last.get("type") == MessageType.BOT and not last.get("text", "").strip():
            session.messages.pop()
        msg_to_store = dict(event)
        msg_to_store.pop("phase", None)
        msg_to_store.pop("delta", None)
        msg_to_store.pop("from_stream_step", None)
        if msg_to_store.get("type") == MessageType.TOOL and msg_to_store.get("tool_id"):
            # Persist the stream's tool_call_id under the canonical key used
            # by replay consumers (and by result-correlation in the branch
            # above), so a tool/result pairing survives across replays.
            msg_to_store["tool_call_id"] = msg_to_store.pop("tool_id")
        if msg_to_store.get("type") == MessageType.TOOL:
            t_type = msg_to_store.get("tool_type") or msg_to_store.get("name")
            if t_type == "update_plan" and isinstance(msg_to_store.get("args"), dict):
                p_items = msg_to_store["args"].get("plan")
                if p_items:
                    try:
                        from johnston.core.base_provider.compaction import _clean_plan_items

                        cleaned = _clean_plan_items(p_items)
                        if cleaned:
                            session.plan = cleaned
                    except Exception:
                        pass
        session.messages.append(msg_to_store)
        session.updated_at = _now()

    if session.listeners:
        _notify_listeners(session, event)


def add_listener(session: Any, cb: Any) -> None:
    if cb not in session.listeners:
        session.listeners.append(cb)


def remove_listener(session: Any, cb: Any) -> None:
    if cb in session.listeners:
        session.listeners.remove(cb)


def _notify_listeners(session: Any, event: Any) -> None:
    for cb in list(session.listeners):
        try:
            cb(event)
        except Exception:
            logger.warning("Session listener callback failed", exc_info=True)


def _now() -> float:
    import time

    return time.time()
