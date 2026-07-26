import os
from typing import Any, Dict

from tools.base import BaseTool, resolve_path
from tools.linter import run_linter


class CreateTool(BaseTool):
    name = "create"
    description = "Create a new file with specified content. Creates parent directories automatically."
    schema = {
        "type": "function",
        "function": {
            "name": "create",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative file path"},
                    "content": {"type": "string", "description": "Full file content"}
                },
                "required": ["path", "content"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        path = resolve_path(args.get("path"))
        content = args.get("content", "").rstrip("\r\n")
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
            linter_output = await run_linter(path)
            return f"Success: file '{path}' saved ({len(content)} bytes).{linter_output}"
        except Exception as e:
            return f"Error creating file '{path}': {e}"
