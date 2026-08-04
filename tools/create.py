import asyncio
import difflib
import os
from typing import Any, Dict

from tools.base import BaseTool, atomic_write_text, resolve_path
from tools.linter import run_linter


def _write_file(path: str, content: str) -> None:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    atomic_write_text(path, content)


class CreateTool(BaseTool):
    name = "create"
    description = "Create a new file or update an existing file with specified content. Creates parent directories automatically."
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

        file_existed = os.path.isfile(path)
        old_content = ""
        if file_existed:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    old_content = f.read()
            except Exception:
                old_content = ""

        try:
            await asyncio.to_thread(_write_file, path, content)
            linter_output = await run_linter(path)

            if file_existed:
                old_lines = old_content.splitlines()
                new_lines = content.splitlines()
                diff_lines = list(
                    difflib.unified_diff(
                        old_lines,
                        new_lines,
                        fromfile=f"a/{path}",
                        tofile=f"b/{path}",
                        lineterm="",
                    )
                )
                if not diff_lines:
                    cnt = len(new_lines) or 1
                    diff_lines = [
                        f"--- a/{path}",
                        f"+++ b/{path}",
                        f"@@ -1,{cnt} +1,{cnt} @@",
                    ] + [" " + line for line in new_lines]

                diff_text = "\n".join(diff_lines).strip()
                diff_part = f"\n\n{diff_text}" if diff_text else ""
                return f"Success: file '{path}' updated ({len(content)} bytes).{linter_output}{diff_part}"
            else:
                return f"Success: file '{path}' created ({len(content)} bytes).{linter_output}"
        except Exception as e:
            return f"Error creating file '{path}': {e}"

