import asyncio
import os
from typing import Any, Dict

from tools.base import BaseTool, atomic_write_text, resolve_path
from tools.linter import run_linter


def _write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    atomic_write_text(path, content)


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
        if os.path.isdir(path):
            return f"Error: '{path}' is a directory, cannot overwrite with file."
        content = (args.get("content") or "").rstrip("\r\n")
        try:
            await asyncio.to_thread(_write_file, path, content)
            linter_output = await run_linter(path)
            return f"Success: file '{path}' saved ({len(content)} bytes).{linter_output}"
        except Exception as e:
            return f"Error creating file '{path}': {e}"
