import os
from typing import Any, Dict

from tools.base import BaseTool, resolve_path, truncate_output


class ReadTool(BaseTool):
    name = "Read"
    description = "Read file content with optional 1-indexed line range pagination."
    schema = {
        "type": "function",
        "function": {
            "name": "Read",
            "description": "Read file content cleanly. Specify path, and optionally start_line and end_line for line range pagination (1-indexed).",
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
        path = resolve_path(args.get("path"))
        if not os.path.exists(path):
            return f"Error: file '{path}' not found."

        ext = os.path.splitext(path)[1].lower()
        if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tiff", ".svg"}:
            from tools.view_image import ViewImageTool
            return await ViewImageTool().execute(args, app)

        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            start = args.get("start_line")
            end = args.get("end_line")

            if start is not None or end is not None:
                s_idx = max(0, (start or 1) - 1)
                e_idx = end if end is not None else len(lines)
                sliced = lines[s_idx:e_idx]
                formatted_lines = [f"{s_idx + i + 1:5d} | {line}" for i, line in enumerate(sliced)]
                content = "".join(formatted_lines)
                return f"=== Lines {s_idx+1}-{min(e_idx, len(lines))} of {len(lines)} in {path} ===\n{content}"

            content = "".join(lines)
            return truncate_output(content, max_chars=8000, hint=f"File has {len(lines)} lines. Use start_line/end_line to read specific ranges.")
        except Exception as e:
            return f"Error reading file '{path}': {e}"
