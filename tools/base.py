import os
from typing import Any, Dict

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
    """Expands user tilde and returns absolute filepath or current working directory."""
    if not path_str:
        return os.getcwd()
    return os.path.abspath(os.path.expanduser(path_str))


def truncate_output(text: str, max_chars: int = 8000, hint: str = "", save_log: bool = True) -> str:
    """Truncates text safely if it exceeds max_chars, saving full output to log file."""
    if len(text) <= max_chars:
        return text

    log_path = os.path.expanduser("~/.johnston/logs/last_tool.log")
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
        footer += f" Full output saved to {log_path}. Use Read tool to inspect full log."
    elif hint:
        footer += f" {hint}"
    footer += "]"
    return truncated + footer


class BaseTool:
    name: str = ""
    description: str = ""
    schema: Dict[str, Any] = None

    def _ensure_context(self, ctx_or_app: Any) -> ToolContext:
        if isinstance(ctx_or_app, ToolContext):
            return ctx_or_app
        return ToolContext(ctx_or_app)

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        raise NotImplementedError
