import os
from typing import Any, Dict

from core.domain.defaults.errors import ToolResult
from tools.base import BaseTool, read_file_text, write_file_text
from tools.cancel import run_cancellable
from tools.utils import format_file_diff, resolve_writable_path


class CreateTool(BaseTool):
    name = "create"
    description = (
        "Create a new file or overwrite an existing file. Automatically creates parent directories. "
        "For partial edits in existing files, use 'edit'."
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
        path, err = resolve_writable_path(ctx, path_arg)
        if err is not None:
            return err

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
            new_lines = content.splitlines()
            cnt = len(new_lines) if content else 0
            if not file_existed:
                return f"[created {path_arg} | {cnt} lines]"
            diff_text = format_file_diff(old_content, content, str(path_arg))
            if not diff_text:
                return f"[unchanged {path_arg} | {cnt} lines]"
            return diff_text

        try:
            result_str = await run_cancellable(_write_and_diff)
            result_str = result_str.strip() if result_str else ""
            return ToolResult.done(content=result_str, display=result_str)
        except Exception as e:
            return ToolResult.error("file", detail=str(e), name=path_arg or path)
