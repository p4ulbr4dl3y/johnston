import json
import os
from typing import Any, Dict

from core.platform_utils import atomic_write_text
from tools.context import ToolContext

__all__ = [
    "resolve_path",
    "write_file_text",
    "read_file_text",
    "try_int",
    "tail_output",
    "make_unified_diff",
    "get_fuzzy_matches",
    "truncate_output",
    "format_tool_error",
    "format_background_notification",
    "BaseTool",
]


def resolve_path(path_str: str | None = None, cwd: str | None = None) -> str:
    """Resolves a path to an absolute path, optionally relative to a base cwd."""
    base = os.path.realpath(os.path.abspath(cwd)) if cwd else os.path.realpath(os.getcwd())
    if not path_str:
        return base
    if os.path.isabs(path_str):
        return os.path.abspath(os.path.expanduser(path_str))
    return os.path.realpath(os.path.join(base, os.path.expanduser(path_str)))


def write_file_text(path: str, content: str) -> None:
    """Ensures parent directory exists and atomically writes text to file."""
    atomic_write_text(path, content)


def read_file_text(path: str) -> str:
    """Reads a text file."""
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def try_int(val: Any, default: int | None = None) -> int | None:
    """Safely converts val to int, returning default on failure."""
    if val is None:
        return default
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def tail_output(text: str, max_chars: int = 2000) -> str:
    """Returns tail of text with a truncation notice if max_chars is exceeded."""
    if not text or len(text) <= max_chars:
        return text
    return f"... [Output truncated, showing last {max_chars} chars]\n{text[-max_chars:]}"


def make_unified_diff(
    old_content: str | list[str],
    new_content: str | list[str],
    fromfile: str = "old",
    tofile: str = "new",
) -> str:
    """Generates unified diff text string from two strings or lists of lines."""
    import difflib

    old_l = old_content if isinstance(old_content, list) else old_content.splitlines()
    new_l = new_content if isinstance(new_content, list) else new_content.splitlines()

    diff_lines = list(difflib.unified_diff(
        old_l,
        new_l,
        fromfile=fromfile,
        tofile=tofile,
        lineterm="",
    ))
    return "\n".join(diff_lines)


def get_fuzzy_matches(word: str, possibilities: list[str], n: int = 3, cutoff: float = 0.4) -> list[str]:
    """Returns close fuzzy matches using difflib."""
    import difflib

    if not word or not possibilities:
        return []
    return difflib.get_close_matches(word, possibilities, n=n, cutoff=cutoff)



def format_tool_error(kind: str, detail: str = "", name: str = "") -> str:
    """Unified error prefix for tool/agent messages.

    Produces `ERR: <kind> '<name>': <detail>` (or `ERR: <kind>` when both name
    and detail are empty). Matches the existing de-facto `ERR:` convention.
    """
    base = f"ERR: {kind}"
    if name:
        base += f" '{name}'"
    if detail:
        base += f": {detail}"
    return base


def format_background_notification(kind: str, name: str, task_id: str, result: str) -> str:
    """Unified template for background-task completion notifications.

    Emitted as a user message when a background shell/subagent finishes:
    `[System Notification] <kind> '<name>' (ID: <task_id>) completed.\n<task_result>\n<result>\n</task_result>`
    """
    return (
        f"[System Notification] {kind} '{name}' (ID: {task_id}) completed.\n"
        f"<task_result>\n{result}\n</task_result>"
    )


def truncate_output(
    text: str,
    max_chars: int = 8000,
    hint: str = "",
    save_log: bool = True,
    tool_name: str = "",
    tool_id: str = "",
    from_end: bool = False,
) -> str:
    """Truncates text safely if it exceeds max_chars, saving full output to a unique log file."""
    if len(text) <= max_chars:
        return text

    from core.config import LOGS_DIR

    log_content = text
    is_json = False
    stripped = text.strip()
    if (stripped.startswith("{") and stripped.endswith("}")) or (stripped.startswith("[") and stripped.endswith("]")):
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, (dict, list)):
                is_json = True
                log_content = json.dumps(parsed, indent=2, ensure_ascii=False)
        except Exception:
            pass

    log_path = None
    if save_log:
        import uuid
        name_prefix = f"{tool_name}_" if tool_name else "tool_"
        unique_id = tool_id if tool_id else uuid.uuid4().hex[:8]
        filename = f"{name_prefix}{unique_id}.log"
        log_path = os.path.join(LOGS_DIR, filename)
        try:
            os.makedirs(LOGS_DIR, exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(log_content)
        except Exception:
            pass

    format_desc = "Format: JSON." if is_json else ("Format: Single-line text." if "\n" not in text else "")

    if from_end:
        truncated = text[-max_chars:]
        header = f"[Output truncated. Showing last {max_chars} chars."
        if save_log:
            header += f" Full output saved to {log_path}."
            if format_desc:
                header += f" {format_desc}"
            if is_json:
                header += " Use read tool or shell (jq/grep) to inspect formatted JSON log."
            elif "\n" not in text:
                header += " Log is single-line (use content_offset). Use read tool or shell (grep/head/tail) to inspect or filter full log."
            else:
                header += " Use read tool or shell (grep/head/tail) to inspect or filter full log."
        if hint:
            header += f" {hint}"
        header += "]\n...\n"
        return header + truncated
    else:
        truncated = text[:max_chars]
        shown_lines = truncated.count("\n") + (1 if truncated else 0)
        next_line = shown_lines + 1
        footer = f"\n... [Output truncated at {max_chars} chars (lines 1-{shown_lines} shown)."
        if save_log:
            footer += f" Full output saved to {log_path}."
            if format_desc:
                footer += f" {format_desc}"
            if is_json:
                footer += " Use read tool or shell (jq/grep) to inspect formatted JSON log."
            elif "\n" not in text:
                footer += " Log is single-line (use content_offset). Use read tool or shell (grep/head/tail) to inspect or filter full log."
            else:
                footer += f" Use read tool (start_line={next_line}) or shell (grep/head/tail) to inspect remaining log."
        if hint:
            footer += f" {hint}"
        footer += "]"
        return truncated + footer


class BaseTool:
    name: str = ""
    description: str = ""
    schema: Dict[str, Any] = None

    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        # Single source of truth for tool descriptions: the class-level
        # `description` attribute is canonical and is propagated into the JSON
        # schema sent to the model. This prevents the class `description` and
        # `schema["function"]["description"]` from drifting out of sync.
        desc = getattr(cls, "description", "")
        schema = getattr(cls, "schema", None)
        if desc and isinstance(schema, dict):
            fn = schema.get("function")
            if isinstance(fn, dict):
                fn["description"] = desc

    def _ensure_context(self, ctx_or_app: Any) -> ToolContext:
        if isinstance(ctx_or_app, ToolContext):
            return ctx_or_app
        if not ctx_or_app:
            return ToolContext(app=None)
        # Pass the agent through to ToolContext so it can extract the host app,
        # subagent flag, and working directory (cwd/project_dir) it carries.
        return ToolContext(app=ctx_or_app)

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> str:
        raise NotImplementedError
