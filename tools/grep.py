import os
import re
from typing import Any, Dict

from tools.base import BaseTool


class GrepTool(BaseTool):
    name = "Grep"
    description = "Search text inside files by regex."
    schema = {
        "type": "function",
        "function": {
            "name": "Grep",
            "description": "Search text inside files matching regex pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern"},
                    "path": {"type": "string", "description": "Directory path (defaults to cwd)"}
                },
                "required": ["pattern"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        pattern = args.get("pattern", "")
        if not pattern:
            return "Error: pattern is required."
        ignore_dirs = {
            ".git", "node_modules", ".venv", "venv", "env", "__pycache__",
            ".johnston", ".gemini", "dist", "build", "out", "target",
            "coverage", ".next", ".nuxt", ".output", ".cache", ".pytest_cache",
            ".ruff_cache", ".idea", ".vscode"
        }
        ignore_extensions = {
            ".png", ".jpg", ".jpeg", ".gif", ".ico", ".svg", ".webp",
            ".pdf", ".zip", ".tar", ".gz", ".7z", ".rar",
            ".db", ".sqlite", ".sqlite3", ".pyc", ".pyo",
            ".woff", ".woff2", ".ttf", ".eot", ".otf",
            ".mp3", ".mp4", ".mov", ".avi", ".mkv", ".wav",
            ".so", ".dylib", ".dll", ".exe", ".bin", ".o", ".a", ".out",
            ".ds_store"
        }
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except Exception as e:
            return f"Error compiling regex '{pattern}': {e}"

        target_path = args.get("path")
        root_dir = os.path.abspath(os.path.expanduser(target_path)) if target_path else os.getcwd()
        results = []
        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d not in ignore_dirs and not d.startswith(".")]
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in ignore_extensions:
                    continue
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, root_dir)
                try:
                    with open(full_path, "r", encoding="utf-8", errors="ignore") as f:
                        for line_num, line in enumerate(f, 1):
                            if regex.search(line):
                                clean_line = line.strip()
                                if len(clean_line) > 150:
                                    clean_line = clean_line[:150] + "..."
                                results.append(f"{rel_path}:{line_num}: {clean_line}")
                                if len(results) >= 50:
                                    break
                except Exception:
                    pass
                if len(results) >= 50:
                    break
            if len(results) >= 50:
                break
        if not results:
            return "No matches found."
        return "\n".join(results)
