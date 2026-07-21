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
