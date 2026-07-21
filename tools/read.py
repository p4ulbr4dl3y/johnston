import os
from typing import Any, Dict

from tools.base import BaseTool


class ReadTool(BaseTool):
    name = "Read"
    description = "Read file content with optional line range pagination."
    schema = {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Read file content. Optionally specify start_line and end_line for range reading.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative file path"},
                    "start_line": {"type": "integer", "description": "Start line number (1-indexed)"},
                    "end_line": {"type": "integer", "description": "End line number (inclusive)"}
                },
                "required": ["path"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        path = os.path.expanduser(args.get("path", ""))
        if not os.path.exists(path):
            return f"Error: file '{path}' not found."

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            start = args.get("start_line")
            end = args.get("end_line")

            if start is not None or end is not None:
                s_idx = max(0, (start or 1) - 1)
                e_idx = end if end is not None else len(lines)
                sliced = lines[s_idx:e_idx]
                content = "".join(sliced)
                return f"=== Lines {s_idx+1}-{min(e_idx, len(lines))} of {len(lines)} in {path} ===\n{content}"

            content = "".join(lines)
            if len(content) > 8000:
                return content[:8000] + f"\n... [truncated. File has {len(lines)} lines. Use start_line/end_line to read more]"
            return content
        except Exception as e:
            return f"Error reading file '{path}': {e}"
