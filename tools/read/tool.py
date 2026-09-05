import logging
import os
from typing import Any, Dict

from core.domain.defaults.errors import ToolResult
from core.infrastructure.converter import DOC_EXTENSIONS
from core.infrastructure.platform.platform_utils import IMAGE_EXTENSIONS
from tools.base import BaseTool, get_fuzzy_matches, resolve_path, try_int
from tools.cancel import run_cancellable
from tools.utils import DEFAULT_LINE_WINDOW, format_line_pagination

logger = logging.getLogger(__name__)


class ReadTool(BaseTool):
    name = "read"
    description = (
        f"Read file contents, inspect directory listings, or view archive contents (ZIP/TAR). "
        f"Converts docs (PDF/DOCX/XLSX/PPTX/EPUB/IPYNB) and images. "
        f"Outputs up to {DEFAULT_LINE_WINDOW} lines with line numbers."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "read",
            "description": (
                "Read file contents, inspect directory listings, or view archive contents (ZIP/TAR). "
                "Converts rich documents (PDF/DOCX/XLSX/PPTX/EPUB/IPYNB) and images (base64 JSON). "
                f"Outputs up to {DEFAULT_LINE_WINDOW} lines with line numbers; paginate using start_line/end_line."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": (
                            "File, directory, archive, or `scheme://...` MCP resource path. "
                            "Relative paths resolve against cwd (from <environment>)."
                        ),
                    },
                    "start_line": {
                        "type": "integer",
                        "minimum": 1,
                        "description": "1-indexed start line. Use with `end_line` to paginate.",
                    },
                    "end_line": {
                        "type": "integer",
                        "minimum": 1,
                        "description": f"1-indexed end line (inclusive). Max range: {DEFAULT_LINE_WINDOW} lines per call.",
                    },
                    "content_offset": {
                        "type": "integer",
                        "minimum": 0,
                        "description": (
                            "Byte offset for minified single-line files or large pastes. "
                            "When set, line numbers are NOT shown."
                        ),
                    },
                },
                "required": ["path"],
            },
        },
    }

    def get_schema(self, is_subagent: bool = False) -> Dict[str, Any]:
        import copy

        schema = copy.deepcopy(self.schema)
        try:
            from core.infrastructure.config.settings import get_settings

            tools_cfg = get_settings().tools
            line_window = tools_cfg.read_line_window
            props = schema.get("function", {}).get("parameters", {}).get("properties", {})
            if "end_line" in props:
                props["end_line"]["description"] = (
                    f"1-indexed end line (inclusive). Max range: {line_window} lines per call."
                )
        except Exception:
            pass
        return schema

    def is_concurrency_safe(self, args: Dict[str, Any] | None = None) -> bool:
        return True

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        import tools.read as read_pkg

        args = args or {}
        ctx = self._ensure_context(ctx)
        raw_path = str(args.get("path") or "").strip()
        if not raw_path:
            return ToolResult.error("params", name="path", detail="missing or empty")

        if "://" in raw_path and not os.path.exists(raw_path):
            from core.infrastructure.mcp import get_mcp_manager

            mcp_mgr = get_mcp_manager()
            try:
                res_data = await mcp_mgr.read_resource_async(raw_path)
                if res_data:
                    contents = res_data.get("contents", [])
                    out_parts = []
                    for c in contents:
                        if isinstance(c, dict):
                            text = c.get("text")
                            if text is not None:
                                out_parts.append(text)
                            elif c.get("blob") is not None:
                                out_parts.append(f"[blob {c.get('mimeType', 'unknown')}]")
                            else:
                                out_parts.append(str(c))
                        else:
                            out_parts.append(str(c))
                    return ToolResult.done(
                        content="\n".join(out_parts).strip() or "[resource empty]",
                        display=f"Resource {raw_path}",
                    )
            except Exception as e:
                logger.debug("Failed to read MCP resource %s: %s", raw_path, e)

        path = resolve_path(raw_path, cwd=ctx.cwd)
        if getattr(ctx, "sandbox_enabled", False):
            from core.infrastructure.platform.sandbox import is_path_readable_in_sandbox

            if not is_path_readable_in_sandbox(path, cwd=ctx.cwd):
                return ToolResult.error("permission", f"sandbox restriction: read not permitted for sensitive path '{path}'")

        # Resolve requested line window up front so it applies to files, directories, and archives.
        start_line = args.get("start_line")
        end_line = args.get("end_line")
        start_line_int = try_int(start_line)
        end_line_int = try_int(end_line)

        def _inspect_path() -> ToolResult | tuple[str, str | None]:
            if not os.path.exists(path):
                parent_dir = os.path.dirname(path) or "."
                hint = ""
                if os.path.exists(parent_dir) and os.path.isdir(parent_dir):
                    filename = os.path.basename(path)
                    entries = [e for e in os.listdir(parent_dir) if not e.startswith(".")]
                    matches = get_fuzzy_matches(filename, entries, n=3, cutoff=0.4)
                    if matches:
                        hint = f" (did you mean: {', '.join(matches)})"
                    elif entries:
                        sample = sorted(entries)[:5]
                        hint = f" (available files: {', '.join(sample)})"
                return ToolResult.error("not_found", detail="not found" + hint, name=path)

            if os.path.isdir(path):
                return read_pkg._inspect_directory(path, start_line_int, end_line_int)

            if read_pkg.is_archive_file(path):
                tools_cfg = read_pkg._tools_settings()
                max_dir_entries = tools_cfg.max_dir_entries if tools_cfg else 60
                return read_pkg._inspect_archive(path, max_dir_entries, start_line_int, end_line_int)

            try:
                file_size = os.path.getsize(path)
                limit = read_pkg.get_max_tool_payload_bytes()
                if file_size > limit:
                    return ToolResult.error(
                        "size_exceeded", detail=f"exceeds {limit // (1024 * 1024)}MB", name=path
                    )
            except OSError as e:
                return ToolResult.error("check", detail=str(e), name=path)

            ext = os.path.splitext(path)[1].lower()
            return ("file", ext)

        probe_res = await run_cancellable(_inspect_path)
        if isinstance(probe_res, ToolResult):
            return probe_res
        _, ext = probe_res

        # Handle image files
        if ext in IMAGE_EXTENSIONS:
            try:
                detail_arg = args.get("detail")
                image_json = await run_cancellable(read_pkg.process_image_file_sync, path, detail_arg)
                import json

                try:
                    summary = json.loads(image_json).get("summary")
                except Exception:
                    summary = None
                return ToolResult.done(content=image_json, display=summary)
            except Exception as e:
                return ToolResult.error("image", detail=str(e), name=path)

        converted_path = None
        # Handle document formats (PDF, DOCX, etc.) via built-in converter
        if ext in DOC_EXTENSIONS:
            try:
                md_text = await run_cancellable(
                    read_pkg.convert_doc_to_markdown_sync,
                    path,
                )
                lines = [ln.rstrip("\r\n") for ln in md_text.splitlines(keepends=True)]
                from tools.base import _write_output_log

                converted_path = _write_output_log(md_text, tool_name="read", ext=".md")
            except Exception as e:
                return ToolResult.error("doc", detail=str(e), name=path)
        else:
            try:
                content_offset = args.get("content_offset")
                if content_offset is not None:
                    content_offset = max(0, try_int(content_offset, 0))

                lines = await run_cancellable(
                    read_pkg._read_file_lines, path, content_offset, start_line_int, end_line_int
                )
            except Exception as e:
                return ToolResult.error("execute", detail=f"read failed: {e}", name=path)

        # For the plain-text path, `lines` is (window_lines, total_line_count).
        if isinstance(lines, tuple):
            window_lines, total_lines = lines
            window_start = start_line_int if (start_line_int and start_line_int > 1) else 1
        else:
            window_lines, total_lines, window_start = lines, None, None

        return format_line_pagination(
            window_lines,
            start_line=start_line,
            end_line=end_line,
            total_lines=total_lines,
            window_start=window_start,
            max_chars=100000,
            path=path,
            converted_path=converted_path,
        )
