import json
import os
import tempfile
from typing import Any, Dict

from tools.context import ToolContext


def resolve_path(path_str: str | None = None, cwd: str | None = None) -> str:
    """Resolves a path to an absolute path, optionally relative to a base cwd."""
    base = os.path.realpath(os.path.abspath(cwd)) if cwd else os.path.realpath(os.getcwd())
    if not path_str:
        return base
    if os.path.isabs(path_str):
        return os.path.abspath(os.path.expanduser(path_str))
    return os.path.realpath(os.path.join(base, os.path.expanduser(path_str)))


def is_protected_config_path(path: str) -> bool:
    """
    True if the path targets Johnston configuration (.johnston/**): permission files,
    global config, mode/rule definitions, or any other file inside a project .johnston dir.
    Agents must not be able to modify these (permission escalation / policy bypass).
    The tool's own worktree store (~/.johnston/worktrees/<id>/...) is exempt for regular files,
    but config files inside a worktree project are still protected.
    """
    abs_path = os.path.realpath(os.path.abspath(path))
    parts = abs_path.split(os.sep)
    for i, part in enumerate(parts):
        if part != ".johnston":
            continue
        rest = parts[i + 1:]
        if not rest:
            return True
        if rest[0] == "worktrees":
            # Tool-owned worktree store: regular project files inside are fine,
            # nested .johnston config dirs are caught by the next component scan.
            continue
        return True
    return False


def atomic_write_text(path: str, content: str) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".johnston-", suffix=".tmp", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except Exception:
                pass
        raise


def atomic_write_json(path: str, data: Any, indent: int = 2) -> None:
    content = json.dumps(data, indent=indent, ensure_ascii=False)
    atomic_write_text(path, content)


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

    from core.config import LAST_TOOL_LOG_FILE, LOGS_DIR

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
            with open(LAST_TOOL_LOG_FILE, "w", encoding="utf-8") as f:
                f.write(log_content)
        except Exception:
            pass
    else:
        log_path = LAST_TOOL_LOG_FILE

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

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        raise NotImplementedError
