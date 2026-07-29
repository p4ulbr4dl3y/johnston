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


def _preview(value: Any, max_chars: int = 1000) -> str:
    text = _redact(str(value))
    if len(text) > max_chars:
        return text[:max_chars] + "... [truncated]"
    return text


def _hash(value: Any) -> str:
    return hashlib.sha256(str(value).encode("utf-8", errors="replace")).hexdigest()


def append_audit_event(event: dict[str, Any]) -> None:
    from core.config import AUDIT_LOG_FILE

    try:
        targets = {AUDIT_LOG_FILE, os.path.join(".johnston", "audit.jsonl")}

        record = {"ts": time.time(), **event}
        line = json.dumps(record, ensure_ascii=False, default=str) + "\n"
        for t in targets:
            try:
                parent = os.path.dirname(t)
                if parent and not os.path.exists(parent):
                    os.makedirs(parent, exist_ok=True)
                with open(t, "a", encoding="utf-8") as f:
                    f.write(line)
            except Exception:
                pass
    except Exception:
        pass


def append_tool_decision(
    *,
    mode: str,
    tool: str,
    decision: str,
    reason: str,
    capabilities: set[str] | list[str] | tuple[str, ...],
    metadata: dict[str, Any] | None = None,
) -> None:
    record: dict[str, Any] = {
        "event": "tool_decision",
        "mode": mode,
        "tool": tool,
        "decision": decision,
        "reason": reason,
        "capabilities": sorted(capabilities),
        **(metadata or {}),
    }
    append_audit_event(record)


def append_tool_result(
    *,
    mode: str,
    tool: str,
    result: Any,
    budget: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> None:
    append_audit_event(
        {
            "event": "tool_result",
            "mode": mode,
            "tool": tool,
            "result_hash": _hash(result),
            "result_preview": _preview(result),
            "budget": budget or {},
            **(metadata or {}),
        }
    )
