import re
from typing import Any, Dict


def _truncate(target: str, max_len: int = 60) -> str:
    """Collapse whitespace and clip a display label to a UI-friendly length."""
    if not isinstance(target, str):
        return str(target) if target else ""
    target = re.sub(r"\s+", " ", target).strip()
    if len(target) > max_len:
        return target[:25] + "..." + target[-32:]
    return target


def extract_tool_display(tool_name: str, args: Dict[str, Any]) -> str:
    """Build a short, human-readable label describing what a tool call targets.

    This is presentation-only metadata for the chat tool chip and is intentionally
    kept out of the core agent loop so business logic stays free of rendering
    concerns. Tool names are matched case-insensitively against the canonical
    lowercase registry names.
    """
    name = (tool_name or "").lower()
    args = args or {}

    if name == "ask_user":
        qs = args.get("questions")
        if isinstance(qs, list) and qs:
            formatted = []
            for q in qs:
                q_text = (q.get("question_text") or q.get("question") or "") if isinstance(q, dict) else ""
                if q_text:
                    formatted.append(q_text[:27] + "..." if len(q_text) > 30 else q_text)
            if formatted:
                return _truncate(", ".join(f'"{t}"' for t in formatted))
        q = args.get("question")
        if q:
            q_text = str(q)
            return _truncate(f'"{q_text[:47] + "..." if len(q_text) > 50 else q_text}"')
        return "ask_user"

    if name == "get_mcp_schema":
        t = args.get("tool") or args.get("server") or tool_name
        return _truncate(str(t))

    if name == "subagent":
        desc = args.get("description") or args.get("prompt") or ""
        return _truncate(f'"{desc}"') if desc else tool_name

    if name in ("manage_task", "manage_subagent"):
        act = args.get("action") or ""
        tid = args.get("task_id") or args.get("subagent_id") or ""
        if act and tid:
            return _truncate(f"{act} {tid}")
        if tid:
            return _truncate(tid)
        if act:
            return _truncate(act)
        return tool_name

        return tool_name

    # Prioritize file path arguments first for file operations
    for key in ("TargetFile", "target_file", "path", "file", "file_path", "filepath", "filename", "image_path"):
        val = args.get(key)
        if isinstance(val, str) and val:
            return _truncate(val)

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
    str_vals = [str(v) for v in args.values() if isinstance(v, str) and v]
    if not str_vals:
        str_vals = [str(v) for v in args.values() if isinstance(v, (int, float)) and v]
    if str_vals:
        return _truncate(str_vals[0])

    return tool_name
