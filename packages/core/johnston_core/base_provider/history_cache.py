import asyncio
import hashlib
import json
import re
from typing import Any, Dict, List, Optional

from johnston_core.infrastructure.runtime.lru import LruCache

_STREAMING_TARGET_RE = re.compile(
    r'"(?:path|command|url|file_path|file|uri|title|prompt|query|action|question|step|task_id|session_id|message|pattern|regex|instruction|tool_name|name|filter)"\s*:\s*"((?:[^"\\]|\\.)*?)(?:"|$)'
)
_STREAMING_FALLBACK_RE = re.compile(
    r'"([a-zA-Z0-9_]+)"\s*:\s*"((?:[^"\\]|\\.)*?)(?:"|$)'
)
_FALLBACK_IGNORE_KEYS = frozenset({"id", "type", "tool", "status", "action"})

_TARGET_SCAN_BACKOFF = 4096


def _extract_streaming_target(buffer: str, scan_from: int = 0, tool_name: str = "") -> str:
    """Extract the first known target field from partial/complete tool JSON."""
    if not buffer:
        return ""

    from johnston_core.infrastructure.runtime.tool_name import normalize_tool_name

    canonical = normalize_tool_name(tool_name) if tool_name else ""
    if canonical == "kill":
        tid_m = re.search(r'"(?:id|task_id|session_id)"\s*:\s*"((?:[^"\\]|\\.)*?)(?:"|$)', buffer)
        if tid_m:
            return tid_m.group(1).strip()

    if canonical == "message_subagent":
        sid_m = re.search(r'"(?:id|session_id)"\s*:\s*"((?:[^"\\]|\\.)*?)(?:"|$)', buffer)
        if sid_m:
            return f"send message to {sid_m.group(1).strip()}"

    if canonical == "invoke_subagent":
        type_m = re.search(r'"(?:type|role)"\s*:\s*"((?:[^"\\]|\\.)*?)(?:"|$)', buffer)
        title_m = re.search(r'"title"\s*:\s*"((?:[^"\\]|\\.)*?)(?:"|$)', buffer)
        role = type_m.group(1).strip() if type_m else ""
        title = title_m.group(1).strip() if title_m else ""
        if role or title:
            from johnston_core.role_registry import get_role_display_name

            role_cap = get_role_display_name(role) if role else "Worker"
            if title:
                return f'{role_cap}: "{title}"'
            return role_cap

    window = buffer[max(0, scan_from - _TARGET_SCAN_BACKOFF) :]
    for m in _STREAMING_TARGET_RE.finditer(window):
        val = m.group(1)
        val_clean = val[:-1] if val.endswith("\\") and not val.endswith("\\\\") else val
        try:
            val = json.loads(f'"{val_clean}"')
        except Exception:
            val = val_clean.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", " ")
        cleaned = str(val).strip()
        if cleaned:
            return cleaned

    if canonical not in ("read", "edit", "create", "shell", "search", "update_plan", "invoke_subagent"):
        for m in _STREAMING_FALLBACK_RE.finditer(window):
            k = m.group(1).lower()
            if k not in _FALLBACK_IGNORE_KEYS:
                val = m.group(2)
                val_clean = val[:-1] if val.endswith("\\") and not val.endswith("\\\\") else val
                try:
                    val = json.loads(f'"{val_clean}"')
                except Exception:
                    val = val_clean.replace('\\"', '"').replace("\\\\", "\\").replace("\\n", " ")
                cleaned = str(val).strip()
                if cleaned:
                    return f"{k}={cleaned}" if "=" not in cleaned else cleaned

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
