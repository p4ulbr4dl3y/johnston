import re
from typing import Any, Dict

# Argument keys whose values must never appear in the display label (secrets).
_SECRET_KEYS = {"api_key", "apikey", "token", "password", "passwd", "secret", "client_secret", "auth"}

# Textual markup-aware escaping: literal [ and ] would otherwise be swallowed as
# style tags, so escape them (and backslashes) for the chat tool chip.
_ESCAPE_RE = re.compile(r"([\[\]\\])")


def _escape_markup(target: str) -> str:
    """Escape markup-significant characters for safe display in the tool chip."""
    return _ESCAPE_RE.sub(r"\\\1", target)


def _is_secret_key(key: str) -> bool:
    return key.strip().lower() in _SECRET_KEYS


def _truncate(target: str, max_len: int = 60) -> str:
    """Collapse whitespace and clip a display label to a UI-friendly length."""
    if not isinstance(target, str):
        return _escape_markup(str(target)) if target else ""
    target = re.sub(r"\s+", " ", target).strip()
    if len(target) > max_len:
        target = target[:25] + "..." + target[-32:]
    return _escape_markup(target)


def extract_tool_display(tool_name: str, args: Dict[str, Any], cwd: str | None = None) -> str:
    """Build a short, human-readable label describing what a tool call targets.

    This is presentation-only metadata for the chat tool chip and is intentionally
    kept out of the core agent loop so business logic stays free of rendering
    concerns. Tool names are matched case-insensitively against the canonical
    lowercase registry names.
    """
    from tools.registry import normalize_tool_name

    raw_name = (tool_name or "").lower()
    name = normalize_tool_name(raw_name)
    args = args or {}

    if name == "ask_user":
        qs = args.get("questions")
        if isinstance(qs, list) and qs:
            formatted = []
            for q in qs:
                q_text = (q.get("question_text") or q.get("question") or "") if isinstance(q, dict) else ""
                if q_text:
                    formatted.append(_truncate(q_text))
            if formatted:
                return _truncate(", ".join(f'"{t}"' for t in formatted))
        q = args.get("question")
        if q:
            q_text = str(q)
            return _truncate(f'"{_truncate(q_text)}"')
        return "ask_user"

    if name == "invoke_subagent":
        desc = args.get("description") or args.get("prompt") or ""
        return _truncate(f'"{desc}"') if desc else tool_name

    if name in ("manage_shell", "manage_subagent"):
        from tools.registry import normalize_tool_args

        nargs = normalize_tool_args(name, args)
        act = nargs.get("action") or ""
        tid = nargs.get("task_id") or ""
        if act and tid:
            if act in ("send_input", "send_message"):
                verb = "send message to" if act == "send_message" else "send input to"
                return _truncate(f"{verb} {tid}")
            return _truncate(f"{act} {tid}")
        if tid:
            return _truncate(tid)
        if act:
            return _truncate(act)
        return tool_name

    # Prioritize file path arguments first for file operations
    for key in ("TargetFile", "target_file", "path", "file", "file_path", "filepath", "filename", "image_path"):
        val = args.get(key)
        if isinstance(val, str) and val:
            return _truncate(val.strip())

    # Generic: prefer a query/prompt argument when present (e.g., search, subagent)
    q_val = args.get("query") or args.get("prompt")
    if isinstance(q_val, str) and q_val:
        return _truncate(f'"{q_val}"')

    # Then other string args (command, question, url)
    for key in ("command", "question", "url"):
        val = args.get(key)
        if isinstance(val, str) and val:
            return _truncate(val)

    questions = args.get("questions")
    if isinstance(questions, list) and questions:
        first = questions[0]
        if isinstance(first, dict):
            txt = first.get("question_text", "")
            if txt:
                return _truncate(txt)

    # Last resort: first non-empty string value, then first numeric value
    # (skipping secret keys so api_key/token/password never leak into the chip).
    str_vals = [
        str(v)
        for k, v in args.items()
        if isinstance(v, str) and v and not _is_secret_key(k)
    ]
    if not str_vals:
        str_vals = [
            str(v)
            for k, v in args.items()
            if isinstance(v, (int, float)) and v and not _is_secret_key(k)
        ]
    if str_vals:
        return _truncate(str_vals[0])

    return tool_name
