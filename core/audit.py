import hashlib
import json
import os
import re
import time
from typing import Any

SECRET_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|password|secret)(\s*[=:]\s*)([^\s,'\"]+)"),
    re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"\bsk-[A-Za-z0-9_-]{12,}\b"),
)


def _redact(value: str) -> str:
    redacted = value
    redacted = SECRET_PATTERNS[0].sub(r"\1\2[REDACTED]", redacted)
    redacted = SECRET_PATTERNS[1].sub("Bearer [REDACTED]", redacted)
    redacted = SECRET_PATTERNS[2].sub("sk-[REDACTED]", redacted)
    return redacted


def _preview(value: Any, *, max_chars: int = 1000) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    value = _redact(value)
    if len(value) <= max_chars:
        return value
    return value[:max_chars] + "...[truncated]"


def _hash(value: Any) -> str:
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def append_trace_event(event: dict[str, Any]) -> None:
    try:
        os.makedirs(".johnston", exist_ok=True)
        record = {
            "ts": time.time(),
            **event,
        }
        with open(os.path.join(".johnston", "trace.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception:
        pass


def append_tool_decision(
    *,
    mode: str,
    tool: str,
    decision: str,
    reason: str,
    capabilities: set[str] | list[str] | tuple[str, ...] = (),
) -> None:
    record: dict[str, Any] = {
        "event": "tool_decision",
        "mode": mode,
        "tool": tool,
        "decision": decision,
        "reason": reason,
        "capabilities": sorted(capabilities),
    }
    append_trace_event(record)
    try:
        os.makedirs(".johnston", exist_ok=True)
        with open(os.path.join(".johnston", "audit.jsonl"), "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": time.time(), **record}, ensure_ascii=False) + "\n")
    except Exception:
        pass


def append_tool_result(
    *,
    mode: str,
    tool: str,
    result: Any,
    budget: dict[str, Any] | None = None,
) -> None:
    append_trace_event(
        {
            "event": "tool_result",
            "mode": mode,
            "tool": tool,
            "result_hash": _hash(result),
            "result_preview": _preview(result),
            "budget": budget or {},
        }
    )
