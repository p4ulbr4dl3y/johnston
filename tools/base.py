import inspect
import json
import os
from typing import Any, Dict, List, Optional

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
    "execute_mcp_tool",
    "check_mcp_role_policy",
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
    """Generates unified diff text string from two strings or lists of lines.

    Uses git's patience diff when available, falling back to difflib.
    """
    from core.git_utils import make_git_diff

    return make_git_diff(
        old_content,
        new_content,
        fromfile=fromfile,
        tofile=tofile,
    )


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
    return f"[System Notification] {kind} '{name}' (ID: {task_id}) completed.\n<task_result>\n{result}\n</task_result>"


def _write_output_log(
    log_content: str,
    *,
    tool_name: str = "",
    tool_id: str = "",
    session_id: str = "",
) -> Optional[str]:
    """Writes full output to a unique log file under LOGS_DIR and returns its path.

    Returns None if logging is skipped (empty content) or the write fails.
    """
    content = log_content or ""
    if not content.strip():
        return None

    import uuid

    from core.config import LOGS_DIR

    if session_id:
        seed = f"{session_id}-{uuid.uuid4().hex[:4]}"
        filename = f"{seed}.log"
    else:
        name_prefix = f"{tool_name}_" if tool_name else "tool_"
        unique_id = tool_id if tool_id else uuid.uuid4().hex[:8]
        filename = f"{name_prefix}{unique_id}.log"
    log_path = os.path.join(LOGS_DIR, filename)
    try:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(content)
    except Exception:
        return None
    return log_path


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

    log_content = text
    is_json = False
    stripped = text.strip()
    # Only attempt JSON parse when the output looks like JSON and is small enough to
    # parse cheaply. For huge outputs, skipping the full parse avoids a costly
    # json.loads/dumps round-trip of the entire string just to label its format.
    looks_like_json = (stripped.startswith("{") and stripped.endswith("}")) or (
        stripped.startswith("[") and stripped.endswith("]")
    )
    if looks_like_json and len(stripped) <= 1_000_000:
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, (dict, list)):
                is_json = True
                log_content = json.dumps(parsed, indent=2, ensure_ascii=False)
        except Exception:
            pass

    log_path = None
    if save_log:
        log_path = _write_output_log(log_content, tool_name=tool_name, tool_id=tool_id)

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


def check_mcp_role_policy(ctx_or_app: Any, tool_name: str, targets: List[str]) -> Optional[str]:
    """Checks the active role's tool policy for an MCP tool call.

    Returns an error string if the tool is disallowed by role policy, else None.
    """
    from core.role_registry import RoleRegistry, role_tool_error

    app_obj = getattr(ctx_or_app, "app", ctx_or_app)
    mode = getattr(app_obj, "mode", "act") if app_obj is not None else "act"
    role_def = RoleRegistry.get_instance().get_role(str(mode).lower())
    for target in targets:
        policy_err = role_tool_error(role_def, target)
        if policy_err:
            return policy_err
    return None


async def execute_mcp_tool(mcp_mgr: Any, tool_name: str, arguments: Dict[str, Any], target_server: Optional[str] = None):
    """Invokes an MCP tool, preferring the async API when available.

    Mirrors the historical dispatch: managers whose type name ends with "Mock" or
    that lack `call_tool_async` use the synchronous `call_tool` path. The
    `target_server` keyword is only forwarded when provided (to preserve callers
    that historically invoked the manager without it).
    """
    kwargs: Dict[str, Any] = {}
    if target_server is not None:
        kwargs["target_server"] = target_server
    if not type(mcp_mgr).__name__.endswith("Mock") and hasattr(mcp_mgr, "call_tool_async"):
        res_or_coro = mcp_mgr.call_tool_async(tool_name, arguments, **kwargs)
    else:
        res_or_coro = mcp_mgr.call_tool(tool_name, arguments, **kwargs)
    return await res_or_coro if inspect.isawaitable(res_or_coro) else res_or_coro


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
