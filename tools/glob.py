import fnmatch
import os
from typing import Any, Dict

from tools.base import IGNORE_DIRS, BaseTool, resolve_path


class GlobTool(BaseTool):
    name = "Glob"
    description = "Search file paths by pattern."
    schema = {
        "type": "function",
        "function": {
            "name": "Glob",
            "description": "Search file paths matching glob pattern.",
            "parameters": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Glob pattern (e.g. *.py)"},
                    "path": {"type": "string", "description": "Directory path (defaults to cwd)"}
                },
                "required": ["pattern"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        pattern = args.get("pattern", "*")
        root_dir = resolve_path(args.get("path"))
        matches = []
        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]
            for file in files:
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, root_dir)
                if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(file, pattern):
                    matches.append(rel_path)
                    if len(matches) >= 100:
                        break
            if len(matches) >= 100:
                break
        if not matches:
            return "No files found matching the pattern."
        return "\n".join(matches)
