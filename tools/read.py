import asyncio
import os
import shutil
import subprocess
import time
from typing import Any, Dict, Tuple

from core.platform_utils import IMAGE_EXTENSIONS
from tools.base import BaseTool, get_fuzzy_matches, resolve_path, try_int

DOC_EXTENSIONS = {
    ".pdf", ".docx", ".pptx", ".xlsx", ".epub"
}

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10 MB limit
_DOC_CACHE: Dict[str, Tuple[float, float, str]] = {}  # key: path, val: (mtime, timestamp, md_text)
MAX_DOC_CACHE = 50
DOC_CACHE_TTL = 600.0  # 10 minutes


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


def process_image_file_sync(path: str, detail: str | None = None) -> str:
    """Synchronous worker to load, validate, resize, and convert image files to Base64 JSON."""
    import base64
    import io
    import json

    from PIL import Image

    try:
        with Image.open(path) as img:
            img_format = (img.format or "JPEG").upper()
            w, h = img.size

            if detail == "low":
                max_dim = 512
            elif detail in ("high", "original"):
                max_dim = 2048
            else:
                max_dim = 1568  # Ideal token-efficient resolution for vision LLMs

            # Convert color modes
            if img.mode in ("RGBA", "LA", "P", "PA", "CMYK"):
                if img.mode in ("RGBA", "LA", "P"):
                    img = img.convert("RGBA")
                    bg = Image.new("RGBA", img.size, (255, 255, 255, 255))
                    alpha_composite = Image.alpha_composite(bg, img)
                    img = alpha_composite.convert("RGB")
                else:
                    img = img.convert("RGB")
                target_format = "JPEG"
                media_type = "image/jpeg"
            elif img_format == "PNG" and max(w, h) <= max_dim and os.path.getsize(path) < 1 * 1024 * 1024:
                img = img.convert("RGB") if img.mode != "RGB" else img
                target_format = "PNG"
                media_type = "image/png"
            else:
                img = img.convert("RGB") if img.mode != "RGB" else img
                target_format = "JPEG"
                media_type = "image/jpeg"

            if max(w, h) > max_dim:
                ratio = max_dim / float(max(w, h))
                new_size = (max(1, int(w * ratio)), max(1, int(h * ratio)))
                img = img.resize(new_size, Image.Resampling.LANCZOS)
                w, h = img.size

            buf = io.BytesIO()
            if target_format == "JPEG":
                img.save(buf, format="JPEG", quality=85, optimize=True)
            else:
                img.save(buf, format="PNG", optimize=True)

            img_bytes = buf.getvalue()
            b64_str = base64.b64encode(img_bytes).decode("ascii")
            file_kb = len(img_bytes) / 1024.0

            summary = f"[Image file: '{path}' ({w}x{h} px, format: {target_format}, size: {file_kb:.1f} KB)]"

            return json.dumps({
                "type": "image",
                "path": path,
                "dimensions": [w, h],
                "media_type": media_type,
                "base64": b64_str,
                "detail": detail or "high",
                "summary": summary,
            }, ensure_ascii=False)
    except Exception as e:
        raise RuntimeError(f"Unable to process image file '{path}': {e}")


class ReadTool(BaseTool):
    name = "read"
    description = "Read files (max 800 lines). Auto-converts PDF/DOCX to Markdown, supports images."
    schema = {
        "type": "function",
        "function": {
            "name": "read",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "start": {"type": "integer", "description": "Start line (1-indexed)"},
                    "end": {"type": "integer", "description": "End line (inclusive)"},
                    "offset": {"type": "integer", "description": "Byte offset"},
                    "detail": {"type": "string", "description": "Image detail: high (default), low, original"},
                    "raw": {"type": "boolean", "description": "Return raw response for URL"}
                },
                "required": ["path"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        ctx = self._ensure_context(app)
        raw_path = str(args.get("path") or "").strip()
        if raw_path.startswith("http://") or raw_path.startswith("https://"):
            from tools.web_fetch import WebFetchTool
            return await WebFetchTool().execute({"url": raw_path, "raw": bool(args.get("raw", False))}, app=app)
        path = resolve_path(raw_path, cwd=ctx.cwd)
        if not os.path.exists(path):
            parent_dir = os.path.dirname(path) or "."
            hint = ""
            if os.path.exists(parent_dir) and os.path.isdir(parent_dir):
                filename = os.path.basename(path)
                entries = [e for e in os.listdir(parent_dir) if not e.startswith(".")]
                matches = get_fuzzy_matches(filename, entries, n=3, cutoff=0.4)
                if matches:
                    hint = f" [Hint: Did you mean one of these in '{parent_dir}': {', '.join(matches)}?]"
                elif entries:
                    sample = sorted(entries)[:5]
                    hint = f" [Hint: Files available in '{parent_dir}': {', '.join(sample)}]"
            return f"ERR: file '{path}' not found{hint}"

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
                return f"ERR: listing '{path}': {e}"

        try:
            file_size = os.path.getsize(path)
            if file_size > MAX_FILE_SIZE:
                return f"ERR: '{path}' exceeds {MAX_FILE_SIZE // (1024*1024)}MB"
        except OSError as e:
            return f"ERR: check '{path}': {e}"

        ext = os.path.splitext(path)[1].lower()

        # Handle image files
        if ext in IMAGE_EXTENSIONS:
            try:
                detail_arg = args.get("detail")
                image_json = await asyncio.to_thread(process_image_file_sync, path, detail_arg)
                return image_json
            except Exception as e:
                return f"ERR: image '{path}': {e}"

        # Handle document formats (PDF, DOCX, etc.) via MarkItDown
        if ext in DOC_EXTENSIONS:
            try:
                md_text = await asyncio.to_thread(convert_doc_to_markdown_sync, path)
                lines = md_text.splitlines(keepends=True)
            except Exception as e:
                return f"ERR: doc '{path}': {e}"
        else:
            try:
                content_offset = args.get("offset", args.get("content_offset"))
                if content_offset is not None:
                    content_offset = max(0, try_int(content_offset, 0))

                def _read_file_lines(file_path: str, offset: int | None):
                    with open(file_path, "rb") as f:
                        if offset:
                            f.seek(offset)
                        raw_bytes = f.read()
                    text_content = raw_bytes.decode("utf-8", errors="replace")
                    return text_content.splitlines(keepends=True)

                lines = await asyncio.to_thread(_read_file_lines, path, content_offset)
            except Exception as e:
                return f"ERR: file '{path}': {e}"

        from tools.utils import format_line_pagination

        start_line = args.get("start", args.get("start_line"))
        end_line = args.get("end", args.get("end_line"))

        raw_lines = [line.rstrip("\r\n") for line in lines]
        return format_line_pagination(
            raw_lines,
            start_line=start_line,
            end_line=end_line,
            max_chars=100000,
            path=path,
        )
