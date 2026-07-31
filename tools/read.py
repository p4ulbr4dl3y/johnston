import asyncio
import os
import shutil
import subprocess
import time
from typing import Any, Dict, Tuple

from tools.base import BaseTool, resolve_path

IMAGE_EXTENSIONS = {
    ".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".ico", ".tiff", ".svg"
}

DOC_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".epub"
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB limit
_DOC_CACHE: Dict[str, Tuple[float, float, str]] = {}  # key: path, val: (mtime, timestamp, md_text)
MAX_DOC_CACHE = 50
DOC_CACHE_TTL = 600.0  # 10 minutes


def clear_doc_cache() -> None:
    _DOC_CACHE.clear()


def get_cached_doc_markdown(path: str) -> str | None:
    try:
        mtime = os.path.getmtime(path)
    except Exception:
        return None

    if path in _DOC_CACHE:
        cached_mtime, cached_ts, text = _DOC_CACHE[path]
        if cached_mtime == mtime and (time.monotonic() - cached_ts < DOC_CACHE_TTL):
            return text
        del _DOC_CACHE[path]
    return None


def set_cached_doc_markdown(path: str, text: str) -> None:
    try:
        mtime = os.path.getmtime(path)
    except Exception:
        return

    if len(_DOC_CACHE) >= MAX_DOC_CACHE:
        oldest_key = min(_DOC_CACHE.keys(), key=lambda k: _DOC_CACHE[k][1])
        del _DOC_CACHE[oldest_key]

    _DOC_CACHE[path] = (mtime, time.monotonic(), text)


def convert_doc_to_markdown_sync(path: str) -> str:
    """Synchronous CPU worker to convert rich documents to markdown via markitdown."""
    cached = get_cached_doc_markdown(path)
    if cached is not None:
        return cached

    result_text = None

    # 1. Try Python API
    try:
        from markitdown import MarkItDown
        md = MarkItDown()
        result = md.convert(path)
        if result and getattr(result, "text_content", None) is not None:
            result_text = result.text_content
    except Exception:
        pass

    # 2. Try CLI fallback
    if result_text is None:
        cli_path = shutil.which("markitdown")
        if cli_path:
            res = subprocess.run([cli_path, path], capture_output=True, text=True, timeout=30)
            if res.returncode == 0 and res.stdout:
                result_text = res.stdout

    if result_text is not None:
        set_cached_doc_markdown(path, result_text)
        return result_text

    raise RuntimeError(
        f"Unable to convert '{path}' with markitdown. "
        "Ensure 'markitdown' Python package or CLI is installed."
    )


class ReadTool(BaseTool):
    name = "read"
    description = "Read file contents with 800-line window pagination. Auto-converts PDF/DOCX to Markdown."
    schema = {
        "type": "function",
        "function": {
            "name": "read",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "start_line": {"type": "integer", "description": "Start line (1-indexed)"},
                    "end_line": {"type": "integer", "description": "End line (inclusive)"},
                    "content_offset": {"type": "integer", "description": "Byte offset"}
                },
                "required": ["path"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        path = resolve_path(args.get("path"))
        if not os.path.exists(path):
            parent_dir = os.path.dirname(path) or "."
            hint = ""
            if os.path.exists(parent_dir) and os.path.isdir(parent_dir):
                import difflib
                filename = os.path.basename(path)
                entries = [e for e in os.listdir(parent_dir) if not e.startswith(".")]
                matches = difflib.get_close_matches(filename, entries, n=3, cutoff=0.4)
                if matches:
                    hint = f" [Hint: Did you mean one of these in '{parent_dir}': {', '.join(matches)}?]"
                elif entries:
                    sample = sorted(entries)[:5]
                    hint = f" [Hint: Files available in '{parent_dir}': {', '.join(sample)}]"
            return f"Error: file '{path}' not found.{hint}"

        if os.path.isdir(path):
            try:
                raw_entries = sorted(os.listdir(path))
                total_count = len(raw_entries)
                MAX_DIR_ENTRIES = 60

                dirs, files = [], []
                for entry in raw_entries:
                    full_p = os.path.join(path, entry)
                    if os.path.isdir(full_p):
                        dirs.append(f"{entry}/")
                    else:
                        files.append(entry)

                formatted = dirs + files
                if len(formatted) > MAX_DIR_ENTRIES:
                    shown = formatted[:MAX_DIR_ENTRIES]
                    content = "\n".join(shown) + f"\n... [{total_count - MAX_DIR_ENTRIES} items truncated. Total: {total_count} items. Use shell tools for deep listing]"
                else:
                    content = "\n".join(formatted) if formatted else "(empty directory)"

                return (
                    f"Path '{path}' is a directory ({total_count} items). [Hint: Use shell tools for deep listing]:\n{content}"
                )
            except Exception as e:
                return f"Error listing directory '{path}': {e}"

        try:
            file_size = os.path.getsize(path)
            if file_size > MAX_FILE_SIZE:
                return f"Error: file '{path}' exceeds maximum readable size of {MAX_FILE_SIZE // (1024*1024)}MB."
        except OSError as e:
            return f"Error checking file '{path}': {e}"

        ext = os.path.splitext(path)[1].lower()

        # Handle image files
        if ext in IMAGE_EXTENSIONS:
            return f"Error: Image files ({ext}) are not supported."

        # Handle document formats (PDF, DOCX, etc.) via MarkItDown
        if ext in DOC_EXTENSIONS:
            try:
                md_text = await asyncio.to_thread(convert_doc_to_markdown_sync, path)
                lines = md_text.splitlines(keepends=True)
            except Exception as e:
                return f"Error converting document '{path}' to Markdown: {e}"
        else:
            try:
                content_offset = args.get("content_offset")
                if content_offset is not None:
                    try:
                        content_offset = max(0, int(content_offset))
                    except (ValueError, TypeError):
                        content_offset = 0

                def _read_file_lines(file_path: str, offset: int | None):
                    with open(file_path, "rb") as f:
                        if offset:
                            f.seek(offset)
                        raw_bytes = f.read()
                    text_content = raw_bytes.decode("utf-8", errors="replace")
                    return text_content.splitlines(keepends=True)

                lines = await asyncio.to_thread(_read_file_lines, path, content_offset)
            except Exception as e:
                return f"Error reading file '{path}': {e}"

        from tools.utils import format_line_pagination

        start_line = args.get("start_line")
        end_line = args.get("end_line")

        raw_lines = [line.rstrip("\r\n") for line in lines]
        return format_line_pagination(
            raw_lines,
            start_line=start_line,
            end_line=end_line,
            max_chars=14000,
            path=path,
        )
