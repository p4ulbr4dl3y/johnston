import asyncio
import os
from typing import Any, Dict

from core.linters_manager import get_linters_manager
from tools.base import BaseTool, make_unified_diff, resolve_path, write_file_text


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
        ctx = self._ensure_context(app)
        path = resolve_path(args.get("path"), cwd=ctx.cwd)
        if os.path.isdir(path):
            return f"ERR: '{path}' is a directory"

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
            await asyncio.to_thread(write_file_text, path, content)
            linter_output = await get_linters_manager().run_for(path)

            if file_existed:
                diff_text = make_unified_diff(old_content, content, fromfile=f"a/{path}", tofile=f"b/{path}")
                if not diff_text:
                    new_lines = content.splitlines()
                    cnt = len(new_lines) or 1
                    diff_lines = [
                        f"--- a/{path}",
                        f"+++ b/{path}",
                        f"@@ -1,{cnt} +1,{cnt} @@",
                    ] + [" " + line for line in new_lines]
                    diff_text = "\n".join(diff_lines)

                diff_part = f"\n\n{diff_text.strip()}" if diff_text.strip() else ""
                return f"OK: file '{path}' updated.{diff_part}{linter_output}"
            else:
                return f"OK: file '{path}' created.{linter_output}"
        except Exception as e:
            return f"ERR: file '{path}': {e}"

