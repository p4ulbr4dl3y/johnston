import asyncio
import inspect
import json
import os
from typing import Any, Dict, Optional, Set

from core.domain.defaults.errors import ToolResult
from core.infrastructure.platform.paths import LOGS_DIR
from core.infrastructure.platform.platform_utils import atomic_write_text
from tools.context import ToolContext

__all__ = [
    "resolve_path",
    "resolve_writable_path",
    "write_file_text",
    "read_file_text",
    "try_int",
    "get_fuzzy_matches",
    "truncate_output",
    "_write_output_log",
    "format_background_notification",
    "execute_mcp_tool",
    "check_mcp_role_policy",
    "confirm_permission",
    "resolve_subagent_identity",
    "_resolve_app",
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


def resolve_writable_path(ctx: Any, path_arg: Any) -> tuple[str, "ToolResult | None"]:
    """Resolves a path argument and rejects missing values or sandbox-blocked writes."""
    from tools.utils import resolve_writable_path as _resolve_writable_path

    return _resolve_writable_path(ctx, path_arg)



def write_file_text(path: str, content: str) -> None:
    """Ensures parent directory exists and atomically writes text to file.

    Resolves symlinks first so writes target the real inode (never clobbering
    the link itself); atomic_write_text refuses read-only/other overrides.
    """
    atomic_write_text(os.path.realpath(path), content)


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


def get_fuzzy_matches(word: str, possibilities: list[str], n: int = 3, cutoff: float = 0.4) -> list[str]:
    """Returns close fuzzy matches using difflib."""
    import difflib

    if not word or not possibilities:
        return []
    return difflib.get_close_matches(word, possibilities, n=n, cutoff=cutoff)


def format_background_notification(
    type_: str,
    title: str,
    task_id: str,
    result: str,
) -> str:
    """Unified template for background-task completion notifications.

    Emitted as a synthetic user message when a background shell/subagent finishes:
    `<notification type="..." id="..." title="...">\n...\n</notification>`
    """
    from core.infrastructure.runtime.xml_utils import escape_xml_attr

    escaped_type = escape_xml_attr(type_)
    escaped_title = escape_xml_attr(title)
    escaped_id = escape_xml_attr(task_id)
    return (
        f'<notification type="{escaped_type}" id="{escaped_id}" title="{escaped_title}">\n'
        f"{result}\n"
        f"</notification>"
    )


def _get_running_loop() -> Any:
    """Return the running event loop, or None if none is running."""
    try:
        return asyncio.get_running_loop()
    except RuntimeError:
        return None


# Keeps fire-and-forget disk writes scheduled from async contexts alive until
# they complete so the coroutine is not garbage-collected before running.
_BACKGROUND_WRITE_TASKS: Set[asyncio.Task] = set()


def _schedule_background(coro: Any) -> None:
    """Schedule ``coro`` on the running loop, holding a reference until done."""
    task = asyncio.ensure_future(coro)
    _BACKGROUND_WRITE_TASKS.add(task)
    task.add_done_callback(_BACKGROUND_WRITE_TASKS.discard)


# Hard cap on a single snapshot log so a runaway tool output cannot fill disk.
MAX_SNAPSHOT_LOG_BYTES = 50 * 1024 * 1024

# Shared default cap for tool output handed to the model (truncate_output and
# the registry's post-MCall truncation must stay in sync).
MAX_TOOL_OUTPUT_CHARS = 8000


def _write_output_log(
    log_content: str, *, tool_name: str = "", ext: str = ".log", unique: bool = True
) -> Optional[str]:
    """Writes full output to a unique snapshot file under LOGS_DIR and returns its path.

    Returns None if logging is skipped (empty content) or the write fails.
    Runs the blocking ``os.makedirs``/``open().write()`` off the event loop via
    ``asyncio.to_thread`` when an async context is active so a large snapshot in
    an async ``execute`` never stalls the loop; falls back to a synchronous write
    for sync callers (no running loop). Content beyond ``MAX_SNAPSHOT_LOG_BYTES``
    is clipped with a marker.
    """
    content = log_content or ""
    if not content.strip():
        return None

    from core.infrastructure.tasks.output import make_log_path

    log_path = make_log_path(tool_name or "tool", unique=unique, ext=ext)
    if not log_path:
        return None

    if len(content) > MAX_SNAPSHOT_LOG_BYTES:
        content = content[:MAX_SNAPSHOT_LOG_BYTES] + "\n... [snapshot clipped at max size]\n"

    def _write() -> None:
        os.makedirs(LOGS_DIR, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as f:
            f.write(content)

    try:
        if _get_running_loop() is not None:
            _schedule_background(asyncio.to_thread(_write))
        else:
            _write()
    except Exception:
        return None
    return log_path


def truncate_output(
    text: str,
    max_chars: int = MAX_TOOL_OUTPUT_CHARS,
    hint: str = "",
    save_log: bool = True,
    tool_name: str = "",
    from_end: bool = False,
    ext: Optional[str] = None,
    log_path: Optional[str] = None,
    unique: bool = True,
) -> str:
    """Truncates text safely if it exceeds max_chars, saving full output to a unique file."""
    if len(text) <= max_chars:
        return text

    if log_path is None and save_log:
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

        file_ext = ext if ext is not None else (".json" if is_json else ".log")
        log_path = _write_output_log(log_content, tool_name=tool_name, ext=file_ext, unique=unique)

    total_lines = text.count("\n") + (1 if text else 0)

    if from_end:
        truncated = text[-max_chars:]
        shown_lines = truncated.count("\n") + (1 if truncated else 0)
        start_line_shown = max(1, total_lines - shown_lines + 1)
        if total_lines > 1:
            line_info = f"lines {start_line_shown}-{total_lines} of {total_lines}"
        else:
            line_info = f"{shown_lines} lines"

        parts = [f"Truncated: last {max_chars} chars ({line_info})"]
        if log_path:
            parts.append(f"Log: {log_path}")
        if hint:
            parts.append(hint)
        header = f"[{' | '.join(parts)}]\n...\n"
        return header + truncated
    else:
        from tools.utils import truncate_leading

        truncated, shown_lines = truncate_leading(text, max_chars)
        next_line = shown_lines + 1
        if total_lines > 1:
            line_info = f"lines 1-{shown_lines} of {total_lines}"
        else:
            line_info = f"{shown_lines} lines"

        parts = [f"Truncated: {line_info}"]
        if log_path:
            parts.append(f"Log: {log_path}")
            if "\n" not in text:
                parts.append(f"Next: read(path='{log_path}', content_offset={max_chars})")
            else:
                parts.append(f"Next: read(path='{log_path}', start_line={next_line})")
        if hint:
            parts.append(hint)
        footer = f"\n... [{ ' | '.join(parts) }]"
        return truncated + footer


def _resolve_app(ctx_or_app: Any) -> Any:
    """Unwrap a ToolContext/agent to the host app the tools call into.

    Returns the host that implements the UI protocol methods (confirm_permission,
    push_screen_wait...) or the object itself when it already is one. A host app is
    recognised directly (it implements ``push_screen_wait``); otherwise a ``.app``
    host link is unwrapped, falling back to the caller-supplied object so headless
    callers degrade to themselves rather than to a dead ``.app`` mock.
    """
    from tools.context import ToolContext

    if isinstance(ctx_or_app, ToolContext):
        return ctx_or_app.host
    if callable(getattr(ctx_or_app, "push_screen_wait", None)):
        return ctx_or_app
    return getattr(ctx_or_app, "app", None) or ctx_or_app


def check_mcp_role_policy(ctx_or_app: Any, target: str) -> Optional[ToolResult]:
    """Checks the active role's tool policy for an MCP tool call.

    Returns an error ToolResult if the tool is disallowed by role policy, else None.
    """
    from core.domain.policies.role_policy import role_tool_error
    from core.role_registry import RoleRegistry

    role_source = _resolve_app(ctx_or_app)
    role = getattr(role_source, "role", "worker") if role_source is not None else "worker"
    role_def = RoleRegistry.get_instance().get_role(str(role).lower())
    return role_tool_error(role_def, target)


def resolve_subagent_identity(*sources: Any) -> tuple[bool, str]:
    """Detect subagent execution from any of ``sources`` (context/agent/host).

    Returns ``(is_subagent, subagent_role)``. The role falls back to ``"worker"``
    when running as a subagent but no role attribute is found on any source.
    Shared by the registry's permission gate and ``confirm_permission`` so the
    detection rules cannot drift between the two call sites.
    """
    live_sources = [s for s in sources if s is not None]
    is_sub = any(getattr(s, "is_subagent", False) is True for s in live_sources)
    raw_role = ""
    for source in live_sources:
        candidate = getattr(source, "subagent_role", "") or getattr(source, "role", "")
        if isinstance(candidate, str) and candidate:
            raw_role = candidate
            break
    return is_sub, (raw_role or ("worker" if is_sub else ""))


async def confirm_permission(
    screen_name: str,
    args: Any,
    reason: str,
    perm_name: str | None = None,
    ctx_or_app: Any = None,
    is_subagent: bool = False,
    subagent_role: str = "",
) -> bool | str:
    """Prompt the user for a tool-permission confirmation via the host.

    Delegates to the host app's ``confirm_permission`` when available (UI hosts)
    and denies otherwise (headless/CLI mode) so the tools layer stays
    UI-independent. ``ctx_or_app`` may be a ToolContext, agent, or host app; it is
    unwrapped with ``_resolve_app`` before calling.
    """
    if not is_subagent or not subagent_role:
        detected_is_sub, detected_role = resolve_subagent_identity(ctx_or_app)
        if not is_subagent:
            is_subagent = detected_is_sub
        if not subagent_role and is_subagent:
            subagent_role = detected_role or "worker"

    confirm = getattr(_resolve_app(ctx_or_app), "confirm_permission", None)
    if callable(confirm):
        return await confirm(
            screen_name,
            args,
            reason,
            perm_name,
            is_subagent=is_subagent,
            subagent_role=subagent_role,
        )
    return False


async def execute_mcp_tool(mcp_mgr: Any, tool_name: str, arguments: Dict[str, Any], target_server: Optional[str] = None):
    """Invokes an MCP tool asynchronously."""
    kwargs = {"target_server": target_server} if target_server is not None else {}
    if hasattr(mcp_mgr, "call_tool_async"):
        res = mcp_mgr.call_tool_async(tool_name, arguments, **kwargs)
    else:
        res = mcp_mgr.call_tool(tool_name, arguments, **kwargs)
    return await res if inspect.isawaitable(res) else res


class BaseTool:
    name: str = ""
    description: str = ""
    schema: Optional[Dict[str, Any]] = None

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
        from tools.context import ToolContext

        if isinstance(ctx_or_app, ToolContext):
            return ctx_or_app
        if not ctx_or_app:
            return ToolContext(app=None)
        # Pass the agent through to ToolContext so it can extract the host app,
        # subagent flag, and working directory (cwd/project_dir) it carries.
        return ToolContext(app=ctx_or_app)

    def get_schema(self, is_subagent: bool = False) -> Dict[str, Any]:
        """Returns tool schema, optionally tailored for subagents."""
        return self.schema

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> "ToolResult":
        raise NotImplementedError
