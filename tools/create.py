import os
from typing import Any, Dict

from core.linters_manager import get_linters_manager
from tools.base import BaseTool, format_tool_error, make_unified_diff, read_file_text, resolve_path, write_file_text
from tools.cancel import run_cancellable


class CreateTool(BaseTool):
    name = "create"
    description = "Create or update a file with content. Creates parent dirs automatically."
    schema = {
        "type": "function",
        "function": {
            "name": "create",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative file path"},
                    "content": {"type": "string", "description": "Full file content"},
                },
                "required": ["path", "content"],
            },
        },
    }

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> str:
        from tools.registry import normalize_tool_args

        args = normalize_tool_args("create", args)
        ctx = self._ensure_context(ctx)
        path = resolve_path(args.get("path"), cwd=ctx.cwd)

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
            return format_tool_error("file", name=path, detail="is a directory")

        content = (args.get("content") or "")
        if isinstance(content, bytes):
            content = content.decode("utf-8", errors="replace")
        content = content.rstrip("\r\n")

        try:
            await run_cancellable(write_file_text, path, content)
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
                return f"file '{path}' updated.{diff_part}{linter_output}"
            else:
                return f"file '{path}' created.{linter_output}"
        except Exception as e:
            return format_tool_error("file", detail=str(e), name=path)
