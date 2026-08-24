"""Presentational tool-call display helpers (textual chip labels).

Moved out of ``core/application/display.py``: this module produces UI-facing
markup (escape_markup / extract_tool_display). Domain and application must not
own rendering-format output, so these helpers live in the infrastructure
presentation area consumed by core widgets and UI tests.
"""
import json
import re
from collections import OrderedDict
from typing import Any, Dict

# Textual markup-aware escaping: literal [ and ] would otherwise be swallowed as
# style tags, so escape them (and backslashes) for the chat tool chip.
_ESCAPE_RE = re.compile(r"([\[\]\\])")

# LRU memo for extract_tool_display keyed by (tool_name, canonical args). The
# agent loop calls this once per tool call for the chip label; multi-tool turns
# with repeated argument signatures hit the cache instead of re-running the
# label logic. Keys are limited to a small canonical representation so two
# distinct arg dicts can't alias an entry.
_DISPLAY_CACHE: "OrderedDict[tuple, str]" = OrderedDict()
_DISPLAY_CACHE_MAX = 128


def escape_markup(target: str) -> str:
    """Escape markup-significant characters for safe display in the tool chip."""
    return _ESCAPE_RE.sub(r"\\\1", target)


def format_compact_dict(d: dict) -> str:
    """Render a tool-args dict as a compact ``{k: v, ...}`` chip label.

    Single format for every non-builtin (MCP/custom) tool: keys are clipped to
    20 chars, values to 35, the whole entry to ~70 chars total; overflow becomes
    a trailing ``...``. Non-dict or empty input yields ``""`` (empty parens).
    """
    if not isinstance(d, dict) or not d:
        return ""

    items = []
    total_len = 0
    overflow = False
    for k, v in d.items():
        k_str = str(k)
        if len(k_str) > 20:
            k_str = k_str[:17] + "..."

        if isinstance(v, str):
            v_clean = v.replace("\n", "\\n")
            if len(v_clean) > 35:
                v_clean = v_clean[:32] + "..."
            v_str = f'"{v_clean}"'
        else:
            v_str = json.dumps(v, ensure_ascii=False, default=str)
            if len(v_str) > 35:
                v_str = v_str[:32] + "..."

        item_str = f"{k_str}: {v_str}"
        if total_len + len(item_str) > 70:
            overflow = True
            break
        items.append(item_str)
        total_len += len(item_str) + 2

    if overflow and items:
        return "{" + ", ".join(items) + ", ...}"
    elif items:
        return "{" + ", ".join(items) + "}"
    else:
        return "{...}"


def truncate(target: str, max_len: int = 60) -> str:
    """Collapse whitespace and clip a display label to a UI-friendly length."""
    if not isinstance(target, str):
        return escape_markup(str(target)) if target else ""
    target = re.sub(r"\s+", " ", target).strip()
    if len(target) > max_len:
        target = target[:25] + "..." + target[-32:]
    return escape_markup(target)


def _canonical_args(args: Dict[str, Any]) -> tuple:
    """Small stable representation of a tool-call argument dict for caching."""
    if not args:
        return ()
    try:
        return (
            tuple(sorted((k, json.dumps(v, ensure_ascii=False, sort_keys=True)) for k, v in args.items()))
            if args
            else ()
        )
    except Exception:
        return (type(args).__name__, repr(args))


def _display_cache_key(tool_name: str, args: Dict[str, Any]) -> tuple:
    return (str(tool_name), _canonical_args(args))


def extract_tool_display(tool_name: str, args: Dict[str, Any]) -> str:
    """Build a short, human-readable label describing what a tool call targets.

    This is presentation-only metadata for the chat tool chip and is intentionally
    kept out of the core agent loop so business logic stays free of rendering
    concerns. Tool names are matched case-insensitively against the canonical
    lowercase registry names. Results are memoized by (tool_name, args) so the
    agent loop doesn't rebuild identical labels on every tool call.
    """
    key = _display_cache_key(tool_name, args)
    hit = _DISPLAY_CACHE.get(key)
    if hit is not None:
        _DISPLAY_CACHE.move_to_end(key)
        return hit

    # Ensure OrderedDict imported for the cache annotation (no runtime dep).
    result = _extract_tool_display_inner(tool_name, args)

    _DISPLAY_CACHE[key] = result
    while len(_DISPLAY_CACHE) > _DISPLAY_CACHE_MAX:
        _DISPLAY_CACHE.popitem(last=False)
    return result


def _extract_tool_display_inner(tool_name: str, args: Dict[str, Any]) -> str:
    from tools.registry import REGISTRY
    from tools.registry import normalize_tool_name as _normalize

    name = _normalize(tool_name)
    args = args if isinstance(args, dict) else {}
    is_builtin = name in REGISTRY

    if not is_builtin:
        # MCP/custom tools: single predefined format — compact ``{k: v, ...}``
        # args label (empty parens when no args).
        return format_compact_dict(args)

    if name == "ask_user":
        qs = args.get("questions")
        if isinstance(qs, list) and qs:
            formatted = []
            for q in qs:
                q_text = q.get("question") if isinstance(q, dict) else ""
                if q_text:
                    formatted.append(truncate(q_text))
            if formatted:
                return truncate(", ".join(f'"{t}"' for t in formatted))
        return ""

    if name == "invoke_subagent":
        title = args.get("title")
        if isinstance(title, str) and title:
            return truncate(f'"{title}"')
        return ""
    if name in ("manage_shell", "manage_subagent"):
        act = args.get("action") or ""
        tid = args.get("session_id" if name == "manage_subagent" else "task_id") or ""
        if act and tid:
            if act in ("send_input", "send_message"):
                verb = "send message to" if act == "send_message" else "send input to"
                return truncate(f"{verb} {tid}")
            return truncate(f"{act} {tid}")
        if tid:
            return truncate(tid)
        if act:
            return truncate(act)
        return ""

    if name == "update_plan":
        plan_data = args.get("plan")
        if isinstance(plan_data, list):
            total = len(plan_data)
            completed = sum(
                1 for item in plan_data if isinstance(item, dict) and item.get("status") == "completed"
            )
            return f"[{completed}/{total} completed]"
        return ""

    if name in ("read", "create", "edit"):
        val = args.get("path")
        if isinstance(val, str) and val:
            return truncate(val.strip())
        return ""

    if name == "shell":
        cmd = args.get("command")
        if isinstance(cmd, str) and cmd:
            return truncate(cmd)
        return ""

    if name == "web_fetch":
        url = args.get("url")
        if isinstance(url, str) and url:
            return truncate(url)
        return ""
