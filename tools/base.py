import asyncio
import inspect
import json
import os
from typing import Any, Dict, Optional, Set

from core.domain.defaults.errors import ToolResult
from core.domain.policies.messages import format_background_notification
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
    "done",
    "fail",
    "async_start",
    "format_header",
    "format_truncation_footer",
    "ERROR_KIND_NOT_FOUND",
    "ERROR_KIND_IS_DIRECTORY",
    "ERROR_KIND_SIZE_EXCEEDED",
    "ERROR_KIND_ENCODING",
    "ERROR_KIND_BINARY_FILE",
    "ERROR_KIND_PERMISSION",
    "ERROR_KIND_SANDBOX",
    "ERROR_KIND_MATCH_NOT_FOUND",
    "ERROR_KIND_MATCH_AMBIGUOUS",
    "ERROR_KIND_PARAMS",
    "ERROR_KIND_TIMEOUT",
    "ERROR_KIND_HTTP_STATUS",
    "ERROR_KIND_NETWORK",
    "ERROR_KIND_BLOCKED",
    "ERROR_KIND_UNAVAILABLE",
    "ERROR_KIND_LIMIT",
    "ERROR_KIND_CONFLICT",
    "ERROR_KIND_CANCELLED",
    "ERROR_KIND_NOTRUNNING",
    "ERROR_KIND_NOTFOUND",
    "ERROR_KIND_NOT_KILLABLE",
    "ERROR_KIND_NOWRITE",
    "ERROR_KIND_KILL",
    "ERROR_KIND_ACTION",
    "ERROR_KIND_SCHEME",
    "ERROR_KIND_UNKNOWN",
    "ERROR_KIND_UNKNOWN_TOOL",
    "ERROR_KIND_EXECUTE",
    "ERROR_KIND_CONTEXT",
    "ERROR_KIND_PROMPT",
    "ERROR_KIND_DENIED",
    "ERROR_KIND_CHECK",
    "ERROR_KIND_LISTING",
    "ERROR_KIND_ARCHIVE",
    "ERROR_KIND_IMAGE",
    "ERROR_KIND_DOC",
    "ERROR_KIND_MANAGER",
    "ERROR_KIND_SETUP",
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
# The effective value reads tools.max_snapshot_log_bytes from config (falling
# back to this constant); kept as the module-level default for direct callers.
MAX_SNAPSHOT_LOG_BYTES = 50 * 1024 * 1024

# Shared default cap for tool output handed to the model (truncate_output and
# the registry's post-MCall truncation must stay in sync). The effective value
# reads tools.max_tool_output_chars from config; this constant is the fallback.
MAX_TOOL_OUTPUT_CHARS = 8000


def _max_tool_output_chars() -> int:
    """Return the configured tool-output cap (tools.max_tool_output_chars)."""
    try:
        from core.infrastructure.config.settings import get_settings

        return get_settings().tools.max_tool_output_chars
    except Exception:
        return MAX_TOOL_OUTPUT_CHARS


def _max_snapshot_log_bytes() -> int:
    """Return the configured snapshot-log cap (tools.max_snapshot_log_bytes)."""
    try:
        from core.infrastructure.config.settings import get_settings

        return get_settings().tools.max_snapshot_log_bytes
    except Exception:
        return MAX_SNAPSHOT_LOG_BYTES


def _write_output_log(
    log_content: str,
    *,
    tool_name: str = "",
    ext: str = ".log",
    unique: bool = True,
    max_bytes: Optional[int] = None,
) -> Optional[str]:
    """Writes full output to a unique snapshot file under LOGS_DIR and returns its path.

    Returns None if logging is skipped (empty content) or the write fails.
    Runs the blocking ``os.makedirs``/``open().write()`` off the event loop via
    ``asyncio.to_thread`` when an async context is active so a large snapshot in
    an async ``execute`` never stalls the loop; falls back to a synchronous write
    for sync callers (no running loop). Content beyond ``max_bytes`` (default
    ``tools.max_snapshot_log_bytes``) is clipped with a marker.
    """
    content = log_content or ""
    if not content.strip():
        return None

    from core.infrastructure.tasks.output import make_log_path

    log_path = make_log_path(tool_name or "tool", unique=unique, ext=ext)
    if not log_path:
        return None

    if max_bytes is None:
        max_bytes = _max_snapshot_log_bytes()
    if len(content) > max_bytes:
        content = content[:max_bytes] + "\n... [snapshot clipped | max size]\n"

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
    max_chars: Optional[int] = None,
    hint: str = "",
    save_log: bool = True,
    tool_name: str = "",
    from_end: bool = False,
    ext: Optional[str] = None,
    log_path: Optional[str] = None,
    unique: bool = True,
) -> str:
    """Truncates text safely if it exceeds max_chars, saving full output to a unique file.

    When ``max_chars`` is None (the default), the configured
    ``tools.max_tool_output_chars`` value is used so config.json takes effect.
    """
    if max_chars is None:
        max_chars = _max_tool_output_chars()
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
            line_info = f"lines {start_line_shown}..{total_lines} of {total_lines}"
        else:
            line_info = f"{shown_lines} lines"

        parts = ["truncated", f"last {max_chars} chars ({line_info})"]
        if log_path:
            parts.append(f"log {log_path}")
        if hint:
            parts.append(hint)
        header = f"[{' | '.join(parts)}]\n...\n"
        return header + truncated
    else:
        from tools.utils import truncate_leading

        truncated, shown_lines = truncate_leading(text, max_chars)
        next_line = shown_lines + 1
        if total_lines > 1:
            line_info = f"lines 1..{shown_lines} of {total_lines}"
        else:
            line_info = f"{shown_lines} lines"

        parts = ["truncated", line_info]
        if log_path:
            parts.append(f"log {log_path}")
            if "\n" not in text:
                parts.append(f"next read(path='{log_path}', content_offset={max_chars})")
            else:
                parts.append(f"next read(path='{log_path}', start_line={next_line})")
        if hint:
            parts.append(hint)
        footer = f"\n... [{' | '.join(parts)}]"
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


# =============================================================================
# Standardized tool output helpers
# =============================================================================
# Wire format (see system prompt <tool_io_reference>):
#   - Success body:  ``[<key1> | <key2> ...]\n<content>``  OR  plain text
#   - Truncated:     body + ``\n... [truncated | log <p> | next <follow-up-call>]``
#   - Error:         ``ERR: <kind> '<name>': <detail>``
#   - Async start:   ``[task started | id <tid> | log <p>]``
#   - Subagent start:``[subagent started | id <sid> | role <r>]``
#   - Cancelled:     ``[cancelled by user]``
#
# These helpers enforce that shape across tools so the model's parser
# (and our own UI) can rely on it. Status, returncode, and side-effect
# hints are kept in ToolResult; the helper emits only the human-readable
# part. The agent loop in core/base_provider/agent.py is the single
# consumer that maps ToolResult -> wire message; nothing else should
# build tool wire content from scratch.

# Canonical error kinds. Adding a new kind? Update the system prompt's
# <tool_io_reference> table in the same change.
ERROR_KIND_NOT_FOUND = "not_found"
ERROR_KIND_IS_DIRECTORY = "is_directory"
ERROR_KIND_SIZE_EXCEEDED = "size_exceeded"
ERROR_KIND_ENCODING = "encoding"
ERROR_KIND_BINARY_FILE = "binary_file"
ERROR_KIND_PERMISSION = "permission"
ERROR_KIND_SANDBOX = "sandbox"
ERROR_KIND_MATCH_NOT_FOUND = "match_not_found"
ERROR_KIND_MATCH_AMBIGUOUS = "match_ambiguous"
ERROR_KIND_PARAMS = "params"
ERROR_KIND_TIMEOUT = "timeout"
ERROR_KIND_HTTP_STATUS = "http_status"
ERROR_KIND_NETWORK = "network"
ERROR_KIND_BLOCKED = "blocked"  # SSRF / private network
ERROR_KIND_UNAVAILABLE = "unavailable"
ERROR_KIND_LIMIT = "limit"  # concurrent subagent cap, etc.
ERROR_KIND_CONFLICT = "conflict"  # file exists, branch mismatch, etc.
ERROR_KIND_CANCELLED = "cancelled"
ERROR_KIND_NOTRUNNING = "notrunning"  # bg task already exited
ERROR_KIND_NOTFOUND = "notfound"  # subagent session not found
ERROR_KIND_NOT_KILLABLE = "notkillable"
ERROR_KIND_NOWRITE = "nowrite"  # stdin closed
ERROR_KIND_KILL = "kill"
ERROR_KIND_ACTION = "action"  # bad action enum value
ERROR_KIND_SCHEME = "scheme"  # non-http(s) url
ERROR_KIND_UNKNOWN = "unknown"  # generic catch-all (kept for legacy callers)
ERROR_KIND_UNKNOWN_TOOL = "unknown_tool"  # tool name not in registry/MCP
ERROR_KIND_EXECUTE = "execute"  # generic execution failure
ERROR_KIND_CONTEXT = "context"  # missing host/app
ERROR_KIND_PROMPT = "prompt"  # user prompt failed (ask_user)
ERROR_KIND_DENIED = "denied"  # user denied permission
ERROR_KIND_CHECK = "check"  # pre-flight stat failed
ERROR_KIND_LISTING = "listing"  # os.listdir failed
ERROR_KIND_ARCHIVE = "archive"  # zip/tar open failed
ERROR_KIND_IMAGE = "image"  # image processing failed
ERROR_KIND_DOC = "doc"  # doc conversion failed
ERROR_KIND_MANAGER = "manager"  # no task manager / host
ERROR_KIND_SETUP = "setup"  # subagent setup failure


def format_header(**kv_pairs: Any) -> str:
    """Render a standardized ``[k1=v1 | k2=v2]`` header.

    Drops empty/None values; coerces non-str values via str(); values
    containing ``|`` or ``]`` are wrapped to keep the header parseable
    by the simple ``<k>=<v>`` rule used by the model.
    """
    parts = []
    for k, v in kv_pairs.items():
        if v is None or v == "":
            continue
        s = str(v)
        if "|" in s or "]" in s or "\n" in s:
            # Should be rare; keep parser simple by switching to repr.
            s = repr(s)
        parts.append(f"{k}={s}")
    if not parts:
        return ""
    return f"[{' | '.join(parts)}]"


def format_truncation_footer(log_path: Optional[str], next_call: Optional[str] = None, **meta: Any) -> str:
    """Build the standard truncation footer.

    ``next_call`` should be a concrete, copy-pasteable tool invocation
    (e.g. ``"read(path='<log>', start_line=N)"``) so the model can
    recover the rest of the output in one step. ``log_path`` alone is
    not enough — the model needs to know HOW to read it.
    """
    parts = ["truncated"]
    if meta.get("line_info"):
        parts.append(meta["line_info"])
    if log_path:
        parts.append(f"log {log_path}")
    if next_call:
        parts.append(f"next {next_call}")
    if meta.get("hint"):
        parts.append(meta["hint"])
    return f"\n... [{' | '.join(parts)}]"


def done(
    content: str = "",
    *,
    display: Optional[str] = None,
    returncode: Optional[int] = None,
    **header_kv: Any,
) -> "ToolResult":
    """Build a successful ToolResult with a standard ``[<header>]`` prefix.

    The header is OPTIONAL: pass nothing for plain content (e.g. when
    the body already starts with its own structural header). Pass at
    least one kwarg to prepend ``[k=v | ...]\n<content>``.
    """
    hdr = format_header(**header_kv)
    body = content or ""
    full = f"{hdr}\n{body}" if hdr else body
    return ToolResult.done(content=full, display=display if display is not None else full, returncode=returncode)


def fail(
    kind: str,
    detail: str = "",
    *,
    name: str = "",
    returncode: Optional[int] = None,
    display: Optional[str] = None,
) -> "ToolResult":
    """Build a standardized error ToolResult.

    ``kind`` MUST be one of the ERROR_KIND_* constants so the model's
    parser can branch reliably. New values need a matching entry in the
    system prompt's <tool_io_reference> table.
    """
    return ToolResult.error(kind, detail=detail, name=name, returncode=returncode, display=display)


def async_start(task_kind: str, task_id: str, log_path: Optional[str] = None, **extra: Any) -> "ToolResult":
    """Build the standard async-started message (background shell, subagent).

    Emits the canonical ``[<task_kind> started | id <tid> | log <p> ...]``
    line that the model can detect to know the call is non-blocking.
    """
    from core.domain.defaults.errors import ToolResultStatus

    body = format_header(**{"task_kind started": task_kind, "id": task_id, "log": log_path, **extra})
    # Use the human-friendly form
    if log_path:
        body = f"[{task_kind} started | id {task_id} | log {log_path}]"
    else:
        body = f"[{task_kind} started | id {task_id}]"
    return ToolResult(status=ToolResultStatus.RUNNING, content=body, display=body)


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
        #
        # BUGFIX: previously we mutated the class's schema dict in-place.
        # When a subclass did not redeclare `schema`, the parent class's dict
        # was shared, so subclass description accidentally rewrote the
        # parent's wire schema. Now we shallow-copy at subclass time so the
        # propagation is local to the subclass.
        desc = getattr(cls, "description", "")
        schema = getattr(cls, "schema", None)
        if not desc or not isinstance(schema, dict):
            return
        # Only copy if `schema` is inherited verbatim from a parent (i.e.
        # `cls` did not assign its own `schema` attribute). This preserves
        # existing copy-on-write semantics for subclasses that DO override
        # the schema, while preventing cross-class mutation when they do not.
        cls_attrs = vars(cls)
        if "schema" not in cls_attrs:
            return
        # Subclass defined its own schema dict — safe to write description in.
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

    def is_concurrency_safe(self, args: Dict[str, Any] | None = None) -> bool:
        """Whether this tool invocation is safe to run concurrently with other safe tools."""
        return False

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> "ToolResult":
        raise NotImplementedError

