"""Canonicalization of raw subagent stream steps into session events."""

from typing import Optional, Sequence

from core.domain.defaults.errors import parse_stream_step, parse_tool_result_step
from core.domain.entities.session import AgentSession


def stream_step_to_session_event(
    step: Sequence,
    text_accumulator: Optional[list] = None,
    from_stream_step: bool = False,
) -> Optional[dict]:
    """Convert a raw generator step tuple into a canonical session event dict."""
    import math

    parsed = parse_stream_step(step)
    if parsed is None:
        return None
    etype = parsed.event_type
    val1 = parsed.val1
    val2 = parsed.val2
    val3 = parsed.val3

    if etype == "thinking_start":
        evt = {"type": "thinking", "text": val1, "phase": "start"}
    elif etype == "thinking_delta":
        evt = {"type": "thinking", "text": val1, "phase": "delta"}
    elif etype == "thinking_end":
        try:
            dur = float(val1)
            if not math.isfinite(dur):
                dur = 0.0
        except (ValueError, TypeError):
            dur = 0.0
        evt = {"type": "thinking", "text": val2, "duration": dur, "phase": "end"}
    elif etype == "thinking":
        # Informational thinking (auto-compaction/retry notices): always final.
        evt = {"type": "thinking", "text": val1, "duration": 0.0, "phase": "end"}
    elif etype == "tool_generating":
        meta = val3 if isinstance(val3, dict) else {}
        evt = {"type": "tool_generating", "tool_type": val1, "target": val2, "meta": meta}
    elif etype == "tool_generating_update":
        meta = val3 if isinstance(val3, dict) else {}
        evt = {"type": "tool_generating_update", "tool_type": val1, "target": val2, "meta": meta}
    elif etype == "tool":
        if text_accumulator:
            text_accumulator[0] = ""
        targs = val3 if isinstance(val3, dict) else {}
        evt = {"type": "tool", "tool_type": val1, "target": val2, "args": targs}
        if parsed.val4:
            evt["tool_id"] = parsed.val4
    elif etype == "tool_result":
        parsed_tr = parse_tool_result_step(step)
        evt = {"type": "tool", "result_text": val1 or parsed_tr.content}
        if parsed_tr.status is not None:
            evt["status"] = parsed_tr.status.value
        if parsed_tr.is_error:
            evt["is_error"] = True
        if parsed_tr.returncode is not None:
            evt["returncode"] = parsed_tr.returncode
        if len(step) > 6 and step[6]:
            # Carry the tool_call_id so consumers can pair a result with its
            # exact start event instead of relying on FIFO order alone.
            evt["tool_id"] = step[6]
    elif etype == "bot_delta":
        if text_accumulator is not None:
            text_accumulator[0] = text_accumulator[0] + val1
            full_text = text_accumulator[0]
        else:
            full_text = val1
        evt = {"type": "bot", "text": full_text, "delta": val1}
    elif etype == "bot_reset":
        if text_accumulator is not None:
            text_accumulator[0] = ""
        evt = {"type": "bot_reset"}
    elif etype in ("bot_text", "outro"):
        if text_accumulator is not None:
            text_accumulator[0] = val1
        evt = {"type": "bot", "text": val1, "final": True}
    elif etype == "queued_user_message":
        if from_stream_step:
            return None
        if text_accumulator is not None:
            text_accumulator[0] = ""
        evt = {"type": "user", "text": val1}
    elif etype == "retry":
        evt = {
            "type": "retry",
            "attempt": val1,
            "max_retries": val2,
            "delay": val3 or 0.0,
            "error": str(parsed.val4) if parsed.val4 is not None else None,
        }
    elif etype == "event_divider":
        evt = {"type": "event_divider", "text": val1 or "Session Compacted"}
    elif etype == "error":
        evt = {"type": "error", "text": str(val1) if val1 is not None else "Error"}
    else:
        return None

    if from_stream_step:
        evt["from_stream_step"] = True
    return evt


def record_session_step(step: tuple, session: AgentSession, text_accumulator: list) -> Optional[dict]:
    """Records an agent execution step into the session in canonical message format.

    Raw stream events (thinking_start/delta/end, bot_delta/text,
    tool_result) are canonicalized here into shared types (thinking/bot/tool)
    before being appended via AgentSession.add_event.
    """
    event = stream_step_to_session_event(step, text_accumulator)
    if event is not None:
        session.add_event(event)
    return event


record_subagent_step = record_session_step
