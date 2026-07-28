import os
import tempfile
from typing import Any, Dict

from core.policy import resolve_workspace_path
from tools.context import ToolContext

IGNORE_DIRS = {
    ".git", "node_modules", ".venv", "venv", "env", "__pycache__",
    ".johnston", ".gemini", "dist", "build", "out", "target",
    "coverage", ".next", ".nuxt", ".output", ".cache", ".pytest_cache",
    ".ruff_cache", ".idea", ".vscode"
}

IGNORE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
    ".pdf", ".zip", ".tar", ".gz", ".7z", ".rar",
    ".db", ".sqlite", ".sqlite3", ".pyc", ".pyo",
    ".woff", ".woff2", ".ttf", ".eot", ".otf",
    ".mp3", ".mp4", ".mov", ".avi", ".mkv", ".wav",
    ".so", ".dylib", ".dll", ".exe", ".bin", ".o", ".a", ".out",
    ".ds_store"
}


def resolve_path(path_str: str | None = None) -> str:
    """Resolves a path and enforces the current workspace boundary."""
    return resolve_workspace_path(path_str)


def atomic_write_text(path: str, content: str) -> None:
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".johnston-", suffix=".tmp", dir=directory, text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise


def truncate_output(text: str, max_chars: int = 8000, hint: str = "", save_log: bool = True) -> str:
    """Truncates text safely if it exceeds max_chars, saving full output to log file."""
    if len(text) <= max_chars:
        return text

    from core.config import LAST_TOOL_LOG_FILE

    log_path = LAST_TOOL_LOG_FILE
    if save_log:
        try:
            os.makedirs(os.path.dirname(log_path), exist_ok=True)
            with open(log_path, "w", encoding="utf-8") as f:
                f.write(text)
        except Exception:
            pass

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
        return ToolContext(ctx_or_app)

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        raise NotImplementedError
