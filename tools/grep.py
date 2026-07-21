import os
import re
from typing import Any, Dict
from tools.base import BaseTool

class GrepTool(BaseTool):
    name = "Grep"
    description = "Search text inside files by regex."

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        pattern = args.get("pattern", "")
        if not pattern:
            return "Error: pattern is required."
        ignore_dirs = {".git", "node_modules", ".venv", "__pycache__", ".tui", ".gemini"}
        ignore_extensions = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".tar", ".gz", ".db", ".sqlite", ".pyc"}
        try:
            regex = re.compile(pattern, re.IGNORECASE)
        except Exception as e:
            return f"Error compiling regex '{pattern}': {e}"
        
        root_dir = os.getcwd()
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
