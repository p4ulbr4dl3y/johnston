import os
from typing import Any, Dict

from core.domain.defaults.config import DEFAULT_TOOL_PAYLOAD_BYTES
from core.domain.defaults.errors import ToolResult
from tools.base import BaseTool, read_file_text, write_file_text
from tools.cancel import run_cancellable
from tools.utils import format_file_diff, resolve_writable_path

DEFAULT_MAX_PAYLOAD_MB = DEFAULT_TOOL_PAYLOAD_BYTES // (1024 * 1024)


class CreateTool(BaseTool):
    name = "create"
    description = (
        "Create a new file or completely overwrite an existing file. Always specify `path` first before `content`. "
        "Parent directories created automatically."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "create",
            "description": (
                "Create a new file or completely overwrite an existing file. Always specify `path` first before `content`. "
                "Parent directories created automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Relative file path to create or overwrite.",
                    },
                    "content": {
                        "type": "string",
                        "description": "Full file content (empty string creates an empty file).",
                    },
                },
                "required": ["path", "content"],
            },
        },
    }

    def get_schema(self, is_subagent: bool = False) -> Dict[str, Any]:
        import copy

        schema = copy.deepcopy(self.schema)
        try:
            from core.infrastructure.config.settings import get_settings

            max_mb = get_settings().tools.max_tool_payload_bytes // (1024 * 1024)
            fn = schema.get("function", {})
            if "description" in fn:
                fn["description"] = fn["description"].replace(f"({DEFAULT_MAX_PAYLOAD_MB}MB)", f"({max_mb}MB)")
        except Exception:
            pass
        return schema

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
            return ToolResult.error("is_directory", name=path, detail="path is an existing directory")

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
            return ToolResult.error("execute", detail=f"write failed: {e}", name=path_arg or path)
