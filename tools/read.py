import asyncio
import os
import shutil
import subprocess
from typing import Any, Dict, List

from tools.base import BaseTool, resolve_path

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tiff", ".svg"
}

DOC_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".epub"
}


def convert_doc_to_markdown_sync(path: str) -> str:
    """Synchronous CPU worker to convert rich documents to markdown via markitdown."""
    # 1. Try Python API
    try:
        from markitdown import MarkItDown
        md = MarkItDown()
        result = md.convert(path)
        if result and getattr(result, "text_content", None) is not None:
            return result.text_content
    except Exception:
        pass

    # 2. Try CLI fallback
    cli_path = shutil.which("markitdown")
    if cli_path:
        res = subprocess.run([cli_path, path], capture_output=True, text=True, timeout=30)
        if res.returncode == 0 and res.stdout:
            return res.stdout

    raise RuntimeError(
        f"Unable to convert '{path}' with markitdown. "
        "Ensure 'markitdown' Python package or CLI is installed."
    )


class ReadTool(BaseTool):
    name = "read"
    description = "Read file content cleanly. Automatically converts PDF/DOCX/XLSX/PPTX to Markdown. Specify path, and optionally start_line and end_line for line range pagination (1-indexed)."
    schema = {
        "type": "function",
        "function": {
            "name": "read",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative file path"},
                    "start_line": {"type": "integer", "description": "Start line number (1-indexed)"},
                    "end_line": {"type": "integer", "description": "End line number (inclusive)"}
                },
                "required": ["path"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        path = resolve_path(args.get("path"))
        if not os.path.exists(path):
            return f"Error: file '{path}' not found."

        ext = os.path.splitext(path)[1].lower()

        # Handle image files via ViewImageTool
        if ext in IMAGE_EXTENSIONS:
            from tools.view_image import ViewImageTool
            return await ViewImageTool().execute(args, app)

        lines: List[str] = []

        # Handle rich documents via markitdown in background thread
        if ext in DOC_EXTENSIONS:
            try:
                md_text = await asyncio.to_thread(convert_doc_to_markdown_sync, path)
                lines = md_text.splitlines(keepends=True)
            except Exception as e:
                return f"Error converting document '{path}' to Markdown: {e}"
        else:
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    lines = f.readlines()
            except Exception as e:
                return f"Error reading file '{path}': {e}"

        from tools.utils import format_line_pagination

        start_line = args.get("start_line")
        end_line = args.get("end_line")

        raw_lines = [line.rstrip("\r\n") for line in lines]
        formatted = format_line_pagination(
            raw_lines,
            start_line=start_line,
            end_line=end_line,
            max_chars=8000,
            hint=f"File has {len(lines)} lines. Use start_line/end_line to read specific ranges.",
        )

        if start_line is not None or end_line is not None:
            s_val = start_line or 1
            e_val = end_line or len(lines)
            return f"=== Lines {s_val}-{min(e_val, len(lines))} of {len(lines)} in {path} ===\n{formatted}"
        return formatted
