import os
import shutil
import subprocess
import threading
import time
from collections import OrderedDict
from typing import Any, Callable, Dict, Tuple

from core.domain.defaults.errors import ToolResult
from core.infrastructure.platform.platform_utils import IMAGE_EXTENSIONS
from tools.base import BaseTool, get_fuzzy_matches, resolve_path, try_int
from tools.cancel import run_cancellable
from tools.utils import DEFAULT_LINE_WINDOW, MAX_TOOL_PAYLOAD_BYTES

DOC_EXTENSIONS = {".pdf", ".docx", ".pptx", ".xlsx", ".epub"}
_DOC_CACHE: "OrderedDict[str, Tuple[float, float, str]]" = OrderedDict()  # key: path, val: (mtime, timestamp, md_text)
MAX_DOC_CACHE = 50
DOC_CACHE_TTL = 600.0  # 10 minutes

_MARKITDOWN_CLS = None
_MARKITDOWN_INSTANCE = None
_LINE_COUNT_CACHE: "OrderedDict[Tuple[str, float, int], int]" = OrderedDict()
MAX_LINE_COUNT_CACHE = 500


def _get_markitdown():
    global _MARKITDOWN_CLS, _MARKITDOWN_INSTANCE
    import markitdown

    current_cls = markitdown.MarkItDown
    if _MARKITDOWN_INSTANCE is None or _MARKITDOWN_CLS is not current_cls:
        _MARKITDOWN_CLS = current_cls
        _MARKITDOWN_INSTANCE = current_cls()
    return _MARKITDOWN_INSTANCE


def _get_file_line_count(file_path: str, mtime: float, size: int) -> int:
    key = (file_path, mtime, size)
    if key in _LINE_COUNT_CACHE:
        _LINE_COUNT_CACHE.move_to_end(key)
        return _LINE_COUNT_CACHE[key]

    total = 0
    last_byte = b""
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(65536):
                total += chunk.count(b"\n")
                last_byte = chunk[-1:]
        if last_byte and last_byte not in (b"\n", b"\r"):
            total += 1
    except Exception:
        return 0

    _LINE_COUNT_CACHE[key] = total
    _LINE_COUNT_CACHE.move_to_end(key)
    while len(_LINE_COUNT_CACHE) > MAX_LINE_COUNT_CACHE:
        _LINE_COUNT_CACHE.popitem(last=False)
    return total


def get_cached_doc_markdown(path: str) -> str | None:
    try:
        mtime = os.path.getmtime(path)
    except Exception:
        return None

    if path in _DOC_CACHE:
        cached_mtime, cached_ts, text = _DOC_CACHE[path]
        if cached_mtime == mtime and (time.monotonic() - cached_ts < DOC_CACHE_TTL):
            _DOC_CACHE.move_to_end(path)
            return text
        del _DOC_CACHE[path]
    return None


def set_cached_doc_markdown(path: str, text: str) -> None:
    try:
        mtime = os.path.getmtime(path)
    except Exception:
        return

    _DOC_CACHE[path] = (mtime, time.monotonic(), text)
    _DOC_CACHE.move_to_end(path)
    while len(_DOC_CACHE) > MAX_DOC_CACHE:
        _DOC_CACHE.popitem(last=False)


def convert_doc_to_markdown_sync(path: str, cancel_event: threading.Event | None = None) -> str:
    """Synchronous CPU worker to convert rich documents to markdown via markitdown."""
    cached = get_cached_doc_markdown(path)
    if cached is not None:
        return cached

    def _interrupted() -> bool:
        return bool(cancel_event and cancel_event.is_set())

    # On cancellation the awaiting coroutine is already gone, so any exception we
    # raise here would be "never retrieved" by asyncio. Return an empty string
    # instead and let the caller's formatting layer decide. This keeps the worker
    # side-effect-free and warning-free.
    if _interrupted():
        return ""

    result_text = None

    # 1. Try Python API
    try:
        md = _get_markitdown()
        result = md.convert(path)
        if result and getattr(result, "text_content", None) is not None:
            result_text = result.text_content
    except Exception:
        pass

    # 2. Try CLI fallback
    if result_text is None and not _interrupted():
        cli_path = shutil.which("markitdown")
        if cli_path:
            proc = subprocess.Popen(
                [cli_path, path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
            )
            try:
                # Poll communicate() in short slices so a cancellation that lands
                # mid-conversion can kill the subprocess promptly instead of
                # leaving it to run up to the full 30s window.
                stdout, _ = _communicate_cancellable(proc, _interrupted, timeout=30)
                if proc.returncode == 0 and stdout:
                    result_text = stdout
            except Exception:
                if proc.poll() is None:
                    proc.kill()
                raise

    if _interrupted():
        return ""
    if result_text is not None:
        set_cached_doc_markdown(path, result_text)
        return result_text

    raise RuntimeError(
        f"Unable to convert '{path}' with markitdown. Ensure 'markitdown' Python package or CLI is installed."
    )


def _communicate_cancellable(
    proc: subprocess.Popen, interrupted: "Callable[[], bool]", timeout: float
) -> "tuple[str, str]":
    """Run ``proc.communicate`` in slices, killing the process if ``interrupted``.

    ``subprocess.Popen.communicate`` is blocking and cannot be interrupted by a
    plain ``threading.Event``. By slicing the wait into small increments we can
    reap the process as soon as cancellation is signalled, closing the pipe it
    holds instead of letting it linger.
    """
    import time as _time

    deadline = _time.monotonic() + timeout
    while True:
        if interrupted():
            if proc.poll() is None:
                proc.kill()
            return proc.communicate()
        remain = deadline - _time.monotonic()
        if remain <= 0:
            if proc.poll() is None:
                proc.kill()
            return proc.communicate()
        try:
            return proc.communicate(timeout=min(0.25, remain))
        except subprocess.TimeoutExpired:
            continue


def process_image_file_sync(path: str, detail: str | None = None, cancel_event: threading.Event | None = None) -> str:
    """Synchronous worker to load, validate, resize, and convert image files to Base64 JSON."""

    def _interrupted() -> bool:
        return bool(cancel_event and cancel_event.is_set())

    # If cancellation already fired the worker should bail silently (see
    # convert_doc_to_markdown_sync): the awaiting coroutine is gone, so an
    # exception here would only log "Future exception was never retrieved".
    if _interrupted():
        return ""

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

            if _interrupted():
                return ""

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

            return json.dumps(
                {
                    "type": "image",
                    "path": path,
                    "dimensions": [w, h],
                    "media_type": media_type,
                    "base64": b64_str,
                    "detail": detail or "high",
                    "summary": summary,
                },
                ensure_ascii=False,
            )
    except Exception as e:
        raise RuntimeError(f"Unable to process image file '{path}': {e}")


class ReadTool(BaseTool):
    name = "read"
    description = (
        f"Read file contents (text, images, PDF/DOCX/XLSX converted to Markdown). Outputs up to {DEFAULT_LINE_WINDOW} lines with line numbers."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "read",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Absolute or relative file path"},
                    "start_line": {"type": "integer", "description": "Start line (1-indexed)"},
                    "end_line": {"type": "integer", "description": "End line (inclusive)"},
                    "content_offset": {
                        "type": "integer",
                        "description": (
                            "Byte offset to continue reading large or minified single-line files. "
                            "Seeks directly to byte position."
                        ),
                    },
                    "detail": {
                        "type": "string",
                        "enum": ["low", "high", "original"],
                        "description": "Image quality mode for vision models ('low', 'high', 'original'). Defaults to 'high'.",
                    },
                },
                "required": ["path"],
            },
        },
    }

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        args = args or {}
        ctx = self._ensure_context(ctx)
        raw_path = str(args.get("path") or "").strip()
        if not raw_path:
            return ToolResult.error("params", name="path", detail="missing or empty")
        path = resolve_path(raw_path, cwd=ctx.cwd)
        if getattr(ctx, "sandbox_enabled", False):
            from core.infrastructure.platform.sandbox import is_path_readable_in_sandbox

            if not is_path_readable_in_sandbox(path, cwd=ctx.cwd):
                return ToolResult.error("permission", f"sandbox restriction: read not permitted for sensitive path '{path}'")
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
                return ToolResult.error("file", detail="not found" + hint, name=path)

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
                        content = (
                            "\n".join(shown)
                            + f"\n... [{total_count - MAX_DIR_ENTRIES} items truncated. Total: {total_count} items. Use shell tools for deep listing]"
                        )
                    else:
                        content = "\n".join(formatted) if formatted else "(empty directory)"

                    xml_entries = [f"<d>{e}</d>" for e in dirs] + [f"<f>{e}</f>" for e in files]
                    if len(xml_entries) > MAX_DIR_ENTRIES:
                        xml_body = "\n".join(xml_entries[:MAX_DIR_ENTRIES])
                        xml_content = f'<dir path="{path}" total="{total_count}" truncated="1">\n{xml_body}\n</dir>'
                    elif xml_entries:
                        xml_body = "\n".join(xml_entries)
                        xml_content = f'<dir path="{path}" total="{total_count}">\n{xml_body}\n</dir>'
                    else:
                        xml_content = f'<dir path="{path}" total="0"/>'

                    return ToolResult.done(
                        content=xml_content,
                        display=f"Path '{path}' is a directory ({total_count} items). [Hint: Use shell tools for deep listing]:\n{content}",
                    )
                except Exception as e:
                    return ToolResult.error("listing", detail=str(e), name=path)

            try:
                file_size = os.path.getsize(path)
                if file_size > MAX_TOOL_PAYLOAD_BYTES:
                    return ToolResult.error(
                        "file", detail=f"exceeds {MAX_TOOL_PAYLOAD_BYTES // (1024 * 1024)}MB", name=path
                    )
            except OSError as e:
                return ToolResult.error("check", detail=str(e), name=path)

            ext = os.path.splitext(path)[1].lower()
            return ("file", ext)

        probe_res = await run_cancellable(_inspect_path)
        if isinstance(probe_res, ToolResult):
            return probe_res
        _, ext = probe_res

        # Resolve the requested line window up front so it applies to all read paths.
        start_line = args.get("start_line")
        end_line = args.get("end_line")
        start_line_int = try_int(start_line)
        end_line_int = try_int(end_line)

        # Handle image files
        if ext in IMAGE_EXTENSIONS:
            try:
                detail_arg = args.get("detail")
                image_json = await run_cancellable(process_image_file_sync, path, detail_arg)
                import json
                try:
                    summary = json.loads(image_json).get("summary")
                except Exception:
                    summary = None
                return ToolResult.done(content=image_json, display=summary)
            except Exception as e:
                return ToolResult.error("image", detail=str(e), name=path)

        converted_path = None
        # Handle document formats (PDF, DOCX, etc.) via MarkItDown
        if ext in DOC_EXTENSIONS:
            try:
                md_text = await run_cancellable(convert_doc_to_markdown_sync, path)
                lines = [ln.rstrip("\r\n") for ln in md_text.splitlines(keepends=True)]
                from tools.base import _write_output_log

                base_name = os.path.splitext(os.path.basename(path))[0]
                converted_path = _write_output_log(md_text, tool_name=f"read_{base_name}", ext=".md")
            except Exception as e:
                return ToolResult.error("doc", detail=str(e), name=path)
        else:
            try:
                content_offset = args.get("content_offset")
                if content_offset is not None:
                    content_offset = max(0, try_int(content_offset, 0))

                def _read_file_lines(file_path: str, offset: int | None, s_line: int | None, e_line: int | None):
                    """Read file lines, optionally bounded to a requested line window.

                    When a start/end line is given, reads only the requested range
                    (inclusive, 1-based) instead of the whole file, avoiding a full
                    buffered read + copy. Trailing newlines are stripped in place.
                    Returns (window_lines, total_line_count) so pagination headers
                    stay accurate even for partial reads.
                    """
                    try:
                        st = os.stat(file_path)
                        mtime, size = st.st_mtime, st.st_size
                    except OSError:
                        mtime, size = 0.0, 0
                    total = _get_file_line_count(file_path, mtime, size)

                    with open(file_path, "rb") as f:
                        if offset:
                            f.seek(offset)
                        if s_line is not None and s_line > 1:
                            # Skip to the requested first line without buffering the whole file.
                            for _ in range(s_line - 1):
                                if not f.readline():
                                    break
                        if e_line is not None:
                            # Read only up to the requested end line.
                            remaining = max(1, e_line - max(1, s_line or 1) + 1)
                        else:
                            remaining = DEFAULT_LINE_WINDOW
                        raw_lines = []
                        for _ in range(remaining):
                            ln = f.readline()
                            if not ln:
                                break
                            raw_lines.append(ln)
                        lines = [ln.rstrip(b"\r\n").decode("utf-8", errors="replace") for ln in raw_lines]
                        return lines, total

                lines = await run_cancellable(_read_file_lines, path, content_offset, start_line_int, end_line_int)
            except Exception as e:
                return ToolResult.error("file", detail=str(e), name=path)

        from tools.utils import format_line_pagination

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
