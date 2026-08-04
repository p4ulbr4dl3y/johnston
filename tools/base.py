import json
import os
import tempfile
from typing import Any, Dict

from tools.context import ToolContext


def resolve_path(path_str: str | None = None) -> str:
    """Resolves a path to an absolute path."""
    if not path_str:
        return os.path.realpath(os.getcwd())
    return os.path.abspath(os.path.expanduser(path_str))


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

    if save_log:
        import uuid
        name_prefix = f"{tool_name}_" if tool_name else "tool_"
        unique_id = tool_id if tool_id else uuid.uuid4().hex[:8]
        filename = f"{name_prefix}{unique_id}.log"
        log_path = os.path.join(LOGS_DIR, filename)
        try:
            os.makedirs(LOGS_DIR, exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(text)
            with open(LAST_TOOL_LOG_FILE, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass
    else:
        log_path = LAST_TOOL_LOG_FILE

    if from_end:
        truncated = text[-max_chars:]
        header = f"[Output truncated. Showing last {max_chars} chars."
        if save_log:
            header += f" Full output saved to {log_path}. Use read tool or shell (grep/head/tail) to inspect or filter full log."
        if hint:
            header += f" {hint}"
        header += "]\n...\n"
        return header + truncated
    else:
        truncated = text[:max_chars]
        footer = f"\n... [Output truncated at {max_chars} chars."
        if save_log:
            footer += f" Full output saved to {log_path}. Use read tool or shell (grep/head/tail) to inspect or filter full log."
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
        if hasattr(ctx_or_app, "app") and not hasattr(ctx_or_app, "push_screen") and getattr(ctx_or_app, "app", None) is not None:
            app = ctx_or_app.app
        else:
            app = ctx_or_app
        is_sub = getattr(ctx_or_app, "is_subagent", False) or (getattr(app, "is_subagent", False) if app else False)
        return ToolContext(app=app, is_subagent=is_sub)

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        raise NotImplementedError
