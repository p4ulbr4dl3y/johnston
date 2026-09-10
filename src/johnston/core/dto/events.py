from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Sequence

from johnston.core.domain.defaults.errors import parse_stream_step, parse_tool_result_step


@dataclass(slots=True, frozen=True)
class StreamEventDTO:
    """Base class for all stream event DTOs."""


@dataclass(slots=True, frozen=True)
class ContentDeltaDTO(StreamEventDTO):
    text: str = ""


@dataclass(slots=True, frozen=True)
class ThinkingDeltaDTO(StreamEventDTO):
    thought: str = ""


@dataclass(slots=True, frozen=True)
class ToolCallDTO(StreamEventDTO):
    tool_name: str
    args: dict[str, Any] = field(default_factory=dict)
    call_id: str = ""


@dataclass(slots=True, frozen=True)
class ToolResultDTO(StreamEventDTO):
    tool_name: str = ""
    content: str = ""
    is_error: bool = False
    status: str = "done"
    returncode: int | None = None


@dataclass(slots=True, frozen=True)
class CompactionEventDTO(StreamEventDTO):
    summary: str = ""


@dataclass(slots=True, frozen=True)
class TurnCompletedDTO(StreamEventDTO):
    duration_s: float = 0.0
    usage: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True, frozen=True)
class ErrorEventDTO(StreamEventDTO):
    message: str
    fatal: bool = False


def parse_event_dto(step: Sequence[Any]) -> StreamEventDTO:
    """Convert raw stream tuple/sequence to StreamEventDTO."""
    if not step:
        raise ValueError("Empty stream step")

    parsed = parse_stream_step(step)
    if parsed is None:
        raise ValueError("Invalid stream step")

    etype = parsed.event_type

    if etype in ("content", "bot_delta", "bot_text", "outro"):
        return ContentDeltaDTO(text=str(parsed.val1 or ""))

    if etype in ("thinking_delta", "thinking_start", "thinking"):
        return ThinkingDeltaDTO(thought=str(parsed.val1 or ""))

    if etype in ("tool", "tool_call"):
        t_name = parsed.val1
        t_args: dict[str, Any] = {}
        call_id = ""

        if isinstance(t_name, dict):
            raw_dict = t_name
            t_name = raw_dict.get("name", "")
            t_args = raw_dict.get("args") or raw_dict.get("arguments") or {}
            call_id = str(raw_dict.get("id", ""))
        else:
            if isinstance(parsed.val3, dict):
                t_args = parsed.val3
            elif isinstance(parsed.val2, dict):
                t_args = parsed.val2
            elif isinstance(parsed.val2, str) and etype == "tool_call":
                try:
                    loaded = json.loads(parsed.val2)
                    if isinstance(loaded, dict):
                        t_args = loaded
                except Exception:
                    pass
            elif isinstance(parsed.val3, str) and etype == "tool":
                try:
                    loaded = json.loads(parsed.val3)
                    if isinstance(loaded, dict):
                        t_args = loaded
                except Exception:
                    pass

            if len(step) > 4 and step[4]:
                call_id = str(step[4])
            elif len(step) > 3 and isinstance(step[3], str):
                call_id = str(step[3])

        return ToolCallDTO(tool_name=str(t_name or ""), args=t_args, call_id=call_id)

    if etype == "tool_result":
        try:
            parsed_tr = parse_tool_result_step(step)
            res_content = parsed_tr.content or str(parsed.val1 or "")
            status = parsed_tr.status.value if parsed_tr.status is not None else "done"
            is_error = parsed_tr.is_error
            returncode = parsed_tr.returncode
        except Exception:
            res_content = str(step[1]) if len(step) > 1 and step[1] is not None else ""
            is_error = bool(step[3]) if len(step) > 3 and step[3] is not None else False
            status = str(step[4]) if len(step) > 4 and step[4] is not None else "done"
            returncode = step[5] if len(step) > 5 and isinstance(step[5], int) else None

        t_name = ""
        if len(step) > 2 and isinstance(step[2], str) and step[2] != "":
            t_name = step[2]
        return ToolResultDTO(
            tool_name=t_name,
            content=res_content,
            is_error=is_error,
            status=status,
            returncode=returncode,
        )

    if etype in ("event_divider", "compaction"):
        return CompactionEventDTO(summary=str(parsed.val1 or ""))

    if etype in ("turn_completed", "turn_complete"):
        dur = float(parsed.val1) if isinstance(parsed.val1, (int, float)) else 0.0
        usage = parsed.val2 if isinstance(parsed.val2, dict) else {}
        return TurnCompletedDTO(duration_s=dur, usage=usage)

    if etype == "error":
        msg = str(parsed.val1 or "Unknown error")
        fatal = bool(parsed.val2) if parsed.val2 is not None else False
        return ErrorEventDTO(message=msg, fatal=fatal)

    raise ValueError(f"Unknown stream event type: {etype}")
