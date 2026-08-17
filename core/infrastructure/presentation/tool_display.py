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

# Argument keys whose values must never appear in the display label (secrets).
_SECRET_KEYS = {"api_key", "apikey", "token", "password", "passwd", "secret", "client_secret", "auth"}

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


def is_secret_key(key: str) -> bool:
    return key.strip().lower() in _SECRET_KEYS


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


def extract_tool_display(tool_name: str, args: Dict[str, Any], cwd: str | None = None) -> str:
    """Build a short, human-readable label describing what a tool call targets.

    This is presentation-only metadata for the chat tool chip and is intentionally
    kept out of the core agent loop so business logic stays free of rendering
    concerns. Tool names are matched case-insensitively against the canonical
    lowercase registry names. Results are memoized by (tool_name, args) so the
    agent loop doesn't rebuild identical labels on every tool call.
    """
    # cwd affects truncate()? No — truncate is arg-only. Cache solely on args.
    key = _display_cache_key(tool_name, args)
    hit = _DISPLAY_CACHE.get(key)
    if hit is not None:
        _DISPLAY_CACHE.move_to_end(key)
        return hit

    # Ensure OrderedDict imported for the cache annotation (no runtime dep).
    result = _extract_tool_display_inner(tool_name, args, cwd)

    _DISPLAY_CACHE[key] = result
    while len(_DISPLAY_CACHE) > _DISPLAY_CACHE_MAX:
        _DISPLAY_CACHE.popitem(last=False)
    return result


def _extract_tool_display_inner(tool_name: str, args: Dict[str, Any], cwd: str | None = None) -> str:
    from tools.registry import normalize_tool_name

    name = normalize_tool_name(tool_name)
    args = args or {}

    if name == "ask_user":
        qs = args.get("questions")
        if isinstance(qs, list) and qs:
            formatted = []
            for q in qs:
                q_text = q.get("question_text") if isinstance(q, dict) else ""
                if q_text:
                    formatted.append(truncate(q_text))
            if formatted:
                return truncate(", ".join(f'"{t}"' for t in formatted))
        return "ask_user"

    if name == "invoke_subagent":
        desc = args.get("description") or args.get("prompt") or ""
        return truncate(f'"{desc}"') if desc else tool_name

    if name in ("manage_shell", "manage_subagent"):
        nargs = args if isinstance(args, dict) else {}
        act = nargs.get("action") or ""
        tid = nargs.get("session_id" if name == "manage_subagent" else "task_id") or ""
        if act and tid:
            if act in ("send_input", "send_message"):
                verb = "send message to" if act == "send_message" else "send input to"
                return truncate(f"{verb} {tid}")
            return truncate(f"{act} {tid}")
        if tid:
            return truncate(tid)
        if act:
            return truncate(act)
        return tool_name

    # Prioritize file path arguments first for file operations
    for key in ("TargetFile", "target_file", "path", "file", "file_path", "filepath", "filename", "image_path"):
        val = args.get(key)
        if isinstance(val, str) and val:
            return truncate(val.strip())

    # Generic: prefer a query/prompt argument when present (e.g., search, subagent)
    q_val = args.get("query") or args.get("prompt")
    if isinstance(q_val, str) and q_val:
        return truncate(f'"{q_val}"')

    # Then other string args (command, question, url)
    for key in ("command", "question", "url"):
        val = args.get(key)
        if isinstance(val, str) and val:
            return truncate(val)

    questions = args.get("questions")
    if isinstance(questions, list) and questions:
        first = questions[0]
        if isinstance(first, dict):
            txt = first.get("question_text", "")
            if txt:
                return truncate(txt)

    # Last resort: first non-empty string value, then first numeric value
    # (skipping secret keys so api_key/token/password never leak into the chip).
    str_vals = [
        str(v)
        for k, v in args.items()
        if isinstance(v, str) and v and not is_secret_key(k)
    ]
    if not str_vals:
        str_vals = [
            str(v)
            for k, v in args.items()
            if isinstance(v, (int, float)) and v and not is_secret_key(k)
        ]
    if str_vals:
        return truncate(str_vals[0])

    return tool_name
