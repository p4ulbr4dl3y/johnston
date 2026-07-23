import os
import re
from typing import Any, Dict

from tools.base import IGNORE_DIRS, IGNORE_EXTENSIONS, BaseTool, resolve_path, truncate_output


class GrepTool(BaseTool):
    name = "grep"
    description = "Search text inside files by regex."
    schema = {
        "type": "function",
        "function": {
            "name": "grep",
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
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except Exception as e:
            return f"Error compiling regex '{pattern}': {e}"

        root_dir = resolve_path(args.get("path"))
        results = []
        for root, dirs, files in os.walk(root_dir):
            dirs[:] = [d for d in dirs if d not in IGNORE_DIRS and not d.startswith(".")]
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in IGNORE_EXTENSIONS:
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
        return truncate_output("\n".join(results), max_chars=8000, hint="Refine pattern or subfolder path argument if needed.")
