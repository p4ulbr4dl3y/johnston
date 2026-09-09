import os
from dataclasses import dataclass
from typing import Any, Dict

from johnston.core.domain.defaults.errors import ToolResult
from johnston.core.tools.base import BaseTool, read_file_text, write_file_text
from johnston.core.tools.cancel import run_cancellable
from johnston.core.tools.utils import format_file_diff, get_max_tool_payload_bytes, resolve_writable_path


@dataclass(frozen=True)
class _ProbeResult:
    is_dir: bool
    existed: bool
    old_content: str
    diff_skipped: bool


class CreateTool(BaseTool):
    name = "create"
    description = (
        "Create a new file or completely overwrite an existing file. Parent directories created automatically."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "create",
            "description": (
                "Create a new file or completely overwrite an existing file. Parent directories created automatically."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "File path to create or overwrite (relative to cwd by default, "
                            "or absolute for external files)."
                        ),
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

    def is_concurrency_safe(self, args: Dict[str, Any] | None = None) -> bool:
        return False

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        args = args or {}
        ctx = self._ensure_context(ctx)
        path_arg = args.get("path")
        path, err = resolve_writable_path(ctx, path_arg)
        if err is not None:
            return err

        def _probe() -> _ProbeResult:
            """Run sync filesystem checks off the event loop."""
            if os.path.isdir(path):
                return _ProbeResult(is_dir=True, existed=False, old_content="", diff_skipped=False)
            if not os.path.isfile(path):
                return _ProbeResult(is_dir=False, existed=False, old_content="", diff_skipped=False)

            try:
                if os.path.getsize(path) > get_max_tool_payload_bytes():
                    return _ProbeResult(is_dir=False, existed=True, old_content="", diff_skipped=True)
            except OSError:
                pass

            old = ""
            try:
                old = read_file_text(path)
            except Exception:
                old = ""
            return _ProbeResult(is_dir=False, existed=True, old_content=old, diff_skipped=False)

        probe = await run_cancellable(_probe)
        if probe.is_dir:
            return ToolResult.error("is_directory", name=path, detail="path is an existing directory")

        raw_content = args.get("content")
        if raw_content is None:
            content = ""
        elif isinstance(raw_content, bytes):
            content = raw_content.decode("utf-8", errors="replace")
        elif not isinstance(raw_content, str):
            content = str(raw_content)
        else:
            content = raw_content
        content = content.rstrip("\r\n")

        def _write() -> None:
            write_file_text(path, content)

        try:
            await run_cancellable(_write)
        except Exception as e:
            return ToolResult.error("execute", detail=f"write failed: {e}", name=path_arg or path)

        new_lines = content.splitlines()
        cnt = len(new_lines) if content else 0

        if not probe.existed:
            result_str = f"[created {path_arg} | {cnt} lines]"
        elif probe.diff_skipped:
            result_str = f"[overwritten {path_arg} | {cnt} lines (diff skipped: file exceeds payload limit)]"
        else:
            try:
                diff_text = format_file_diff(probe.old_content, content, str(path_arg))
                result_str = diff_text if diff_text else f"[unchanged {path_arg} | {cnt} lines]"
            except Exception:
                result_str = f"[overwritten {path_arg} | {cnt} lines]"

        result_str = result_str.strip() if result_str else ""
        return ToolResult.done(content=result_str, display=result_str)
