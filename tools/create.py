import os
from typing import Any, Dict

from core.domain.defaults.errors import ToolResult
from core.infrastructure.runtime.git_utils import make_git_diff
from tools.base import BaseTool, read_file_text, resolve_path, write_file_text
from tools.cancel import run_cancellable


class CreateTool(BaseTool):
    name = "create"
    description = (
        "Create a new file or overwrite an existing file. Automatically creates parent directories. "
        "For partial edits in existing files, use 'edit' or 'multi_edit'."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "create",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative file path"},
                    "content": {"type": "string", "description": "Full content of the file"},
                },
                "required": ["path", "content"],
            },
        },
    }

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        args = args or {}
        ctx = self._ensure_context(ctx)
        path_arg = args.get("path")
        if not path_arg or not str(path_arg).strip():
            return ToolResult.error("params", name="path", detail="missing or empty")
        path = resolve_path(path_arg, cwd=ctx.cwd)

        def _probe():
            """Run sync filesystem checks off the event loop, returning (existed, old_content)."""
            if os.path.isdir(path):
                return (False, "isdir")
            existed = os.path.isfile(path)
            old = ""
            if existed:
                try:
                    old = read_file_text(path)
                except Exception:
                    old = ""
            return (existed, old)

        file_existed, old_content = await run_cancellable(_probe)
        if not file_existed and old_content == "isdir":
            return ToolResult.error("file", name=path, detail="is a directory")

        content = (args.get("content") or "")
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        content = content.rstrip("\r\n")

        def _write_and_diff():
            write_file_text(path, content)
            if not file_existed:
                return None
            diff_text = make_git_diff(old_content, content, fromfile=f"a/{path}", tofile=f"b/{path}")
            if not diff_text:
                new_lines = content.splitlines()
                cnt = len(new_lines) or 1
                diff_lines = [
                    f"--- a/{path}",
                    f"+++ b/{path}",
                    f"@@ -1,{cnt} +1,{cnt} @@",
                ] + [" " + line for line in new_lines]
                diff_text = "\n".join(diff_lines)
            return diff_text

        try:
            diff_text = await run_cancellable(_write_and_diff)
            if file_existed:
                diff_part = f"\n\n{diff_text.strip()}" if diff_text and diff_text.strip() else ""
                return ToolResult.done(f"file '{path}' updated.{diff_part}")
            else:
                return ToolResult.done(f"file '{path}' created.")
        except Exception as e:
            return ToolResult.error("file", detail=str(e), name=path)
