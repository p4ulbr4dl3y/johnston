import asyncio
import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from core.infrastructure.runtime.lru import LruCache

_STREAMING_TARGET_RE = re.compile(
    r'"(?:path|command|url|file_path|file|uri|title|prompt|query|action|question|step|task_id|session_id|message)"\s*:\s*"((?:[^"\\]|\\.)*?)"'
)

_TARGET_SCAN_BACKOFF = 4096


def _extract_streaming_target(buffer: str, scan_from: int = 0, tool_name: str = "") -> str:
    """Extract the first known target field from partial/complete tool JSON."""
    if not buffer:
        return ""

    from core.infrastructure.runtime.tool_name import normalize_tool_name

    canonical = normalize_tool_name(tool_name) if tool_name else ""
    if canonical in ("manage_shell", "manage_subagent"):
        act_m = re.search(r'"action"\s*:\s*"((?:[^"\\]|\\.)+?)"', buffer)
        tid_m = re.search(r'"(?:task_id|session_id)"\s*:\s*"((?:[^"\\]|\\.)+?)"', buffer)
        act = act_m.group(1).strip() if act_m else ""
        tid = tid_m.group(1).strip() if tid_m else ""
        if act and tid:
            if act in ("send_input", "send_message"):
                verb = "send message to" if act == "send_message" else "send input to"
                return f"{verb} {tid}"
            return f"{act} {tid}"
        if tid:
            return tid
        if act:
            return act

    window = buffer[max(0, scan_from - _TARGET_SCAN_BACKOFF) :]
    for m in _STREAMING_TARGET_RE.finditer(window):
        val = m.group(1)
        try:
            val = json.loads(f'"{val}"')
        except Exception:
            val = val.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", " ")
        cleaned = str(val).strip()
        if cleaned:
            return cleaned
    return ""


def _get_tools_digest(tools: Optional[List[Dict[str, Any]]]) -> str:
    if not tools:
        return ""
    return hashlib.sha256(repr(tools).encode("utf-8")).hexdigest()


def serialize_messages_key(msgs: List[Dict[str, Any]]) -> bytes:
    """Return a stable memoization key for a message list."""
    out = []
    for m in msgs:
        out.append(str(m.get("role")))
        c = m.get("content")
        if isinstance(c, str):
            out.append(c)
        elif c is None:
            out.append("")
        else:
            out.append(str(c))
        out.append(str(m.get("tool_call_id") or ""))
        tc = m.get("tool_calls")
        if tc and isinstance(tc, list):
            tc_parts = []
            for item in tc:
                if isinstance(item, dict):
                    fn = item.get("function") or {}
                    tc_parts.append(f"{item.get('id')}:{fn.get('name')}:{fn.get('arguments')}")
                else:
                    tc_parts.append(str(item))
            out.append("|".join(tc_parts))
        elif tc:
            out.append(str(tc))
        else:
            out.append("")
    return ("\x1f".join(out)).encode("utf-8")


_SANITIZE_CACHE_MAX = 64
_SANITIZE_CACHE: "LruCache[bytes, List[Dict[str, Any]]]" = LruCache(_SANITIZE_CACHE_MAX)


def _cache_sanitize_get(encoded_history: bytes) -> Optional[List[Dict[str, Any]]]:
    return _SANITIZE_CACHE.get(encoded_history)


def _cache_sanitize_put(encoded_history: bytes, sanitized: List[Dict[str, Any]]) -> None:
    _SANITIZE_CACHE.put(encoded_history, sanitized)


async def sanitize_history_cached(agent: Any, history: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Memoized, event-loop-friendly ``sanitize_history_for_model``."""
    key = serialize_messages_key(history)
    cached = _cache_sanitize_get(key)
    if cached is not None:
        return cached

    sanitized = await asyncio.to_thread(agent.sanitize_history_for_model, history)
    _cache_sanitize_put(key, sanitized)
    return sanitized
