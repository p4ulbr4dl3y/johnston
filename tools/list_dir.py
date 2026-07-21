import os
from typing import Any, Dict

from tools.base import IGNORE_DIRS, BaseTool, resolve_path


class ListDirTool(BaseTool):
    name = "ListDir"
    description = "List contents of a directory (files and subdirectories at 1-level depth)."
    schema = {
        "type": "function",
        "function": {
            "name": "ListDir",
            "description": "List contents of a directory (files and subdirectories at 1-level depth).",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (defaults to cwd)"}
                }
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        path = resolve_path(args.get("path"))

        if not os.path.exists(path):
            return f"Error: path '{path}' does not exist."
        if not os.path.isdir(path):
            return f"Error: path '{path}' is not a directory."

        try:
            entries = os.listdir(path)
            dirs = []
            files = []

            for entry in entries:
                if entry in IGNORE_DIRS or entry.startswith("."):
                    continue
                full_entry = os.path.join(path, entry)
                if os.path.isdir(full_entry):
                    dirs.append(f"[DIR]  {entry}/")
                else:
                    try:
                        size = os.path.getsize(full_entry)
                        files.append(f"[FILE] {entry} ({size} bytes)")
                    except Exception:
                        files.append(f"[FILE] {entry}")

            dirs.sort()
            files.sort()
            result = dirs + files

            if not result:
                return f"Directory '{path}' is empty."

            return f"=== Directory contents of {path} ===\n" + "\n".join(result)
        except Exception as e:
            return f"Error listing directory '{path}': {e}"
