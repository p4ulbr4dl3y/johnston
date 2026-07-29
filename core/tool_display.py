import os
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

    if name == "analyze_image":
        img_path = args.get("path") or args.get("image_path") or ""
        prompt_val = args.get("prompt") or args.get("question") or ""
        base_name = os.path.basename(img_path) if img_path else ""
        short_prompt = (prompt_val[:45] + "...") if len(prompt_val) > 45 else prompt_val
        if short_prompt and base_name:
            return _truncate(f'{base_name} — "{short_prompt}"')
        if short_prompt:
            return _truncate(f'"{short_prompt}"')
        if base_name:
            return _truncate(base_name)
        if img_path:
            return _truncate(img_path)
        return tool_name

    # Generic: prefer a query/prompt argument when present
    q_val = args.get("query") or args.get("prompt")
    if isinstance(q_val, str) and q_val:
        return _truncate(f'"{q_val}"')

    # Then prefer meaningful string args in a sensible priority order
    for key in ("path", "file", "command", "question", "url", "image_path"):
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
