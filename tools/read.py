import logging
import os
import threading
import time
from typing import Any, Dict, Tuple

from core.domain.defaults.errors import ToolResult
from core.domain.defaults.git_excludes import DEFAULT_IGNORE_DIRS
from core.infrastructure.converter import DOC_EXTENSIONS
from core.infrastructure.platform.platform_utils import IMAGE_EXTENSIONS
from core.infrastructure.runtime.lru import LruCache
from tools.base import BaseTool, get_fuzzy_matches, resolve_path, try_int
from tools.cancel import run_cancellable
from tools.utils import DEFAULT_LINE_WINDOW, get_max_tool_payload_bytes

logger = logging.getLogger(__name__)

MAX_DOC_CACHE = 50
DOC_CACHE_TTL = 600.0  # 10 minutes
MAX_LINE_COUNT_CACHE = 500

_DOC_CACHE: "LruCache[str, Tuple[float, float, str]]" = LruCache(MAX_DOC_CACHE)  # key: path, val: (mtime, timestamp, md_text)
_LINE_COUNT_CACHE: "LruCache[Tuple[str, float, int], int]" = LruCache(MAX_LINE_COUNT_CACHE)


def _tools_settings():
    """Return the tools config, falling back to module defaults on any failure."""
    try:
        from core.infrastructure.config.settings import get_settings

        return get_settings().tools
    except Exception:
        return None


def _get_file_line_count(file_path: str, mtime: float, size: int) -> int:
    key = (file_path, mtime, size)
    cached = _LINE_COUNT_CACHE.get(key)
    if cached is not None:
        return cached

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

    tools = _tools_settings()
    line_cap = tools.line_count_cache_max if tools else MAX_LINE_COUNT_CACHE
    _LINE_COUNT_CACHE.maxsize = line_cap
    _LINE_COUNT_CACHE.put(key, total)
    return total


def get_cached_doc_markdown(path: str) -> str | None:
    try:
        mtime = os.path.getmtime(path)
    except Exception:
        return None

    tools = _tools_settings()
    doc_ttl = tools.doc_cache_ttl if tools else DOC_CACHE_TTL
    cached = _DOC_CACHE.get(path)
    if cached is not None:
        cached_mtime, cached_ts, text = cached
        if cached_mtime == mtime and (time.monotonic() - cached_ts < doc_ttl):
            return text
        del _DOC_CACHE[path]
    return None


def set_cached_doc_markdown(path: str, text: str) -> None:
    try:
        mtime = os.path.getmtime(path)
    except Exception:
        return

    tools = _tools_settings()
    doc_cap = tools.max_doc_cache if tools else MAX_DOC_CACHE
    _DOC_CACHE.maxsize = doc_cap
    _DOC_CACHE.put(path, (mtime, time.monotonic(), text))



def convert_doc_to_markdown_sync(
    path: str,
    cancel_event: threading.Event | None = None,
    **_kwargs: Any,
) -> str:
    """Synchronous CPU worker to convert rich documents to markdown."""
    cached = get_cached_doc_markdown(path)
    if cached is not None:
        return cached

    def _interrupted() -> bool:
        return bool(cancel_event and cancel_event.is_set())

    if _interrupted():
        return ""

    result_text = None

    try:
        from core.infrastructure.converter import convert_file

        result_text = convert_file(path)
    except Exception as exc:
        logger.debug("Built-in document converter error for %s: %s", path, exc)

    if _interrupted():
        return ""
    if result_text is not None:
        if result_text.strip():
            set_cached_doc_markdown(path, result_text)
        return result_text

    raise RuntimeError(
        f"Unable to convert '{path}' to markdown."
    )


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

    tools = _tools_settings()
    dim_low = tools.image_dimension_low if tools else 512
    dim_high = tools.image_dimension_high if tools else 2048
    dim_default = tools.max_image_dimension if tools else 1568
    png_keep_bytes = tools.image_png_keep_bytes if tools else 1 * 1024 * 1024

    try:
        with Image.open(path) as img:
            img_format = (img.format or "JPEG").upper()
            w, h = img.size

            if detail == "low":
                max_dim = dim_low
            elif detail in ("high", "original"):
                max_dim = dim_high
            else:
                max_dim = dim_default  # Ideal token-efficient resolution for vision LLMs

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
            elif img_format == "PNG" and max(w, h) <= max_dim and os.path.getsize(path) < png_keep_bytes:
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

            summary = f"[image {path} | {w}x{h} | {target_format.lower()} | {file_kb:.1f} KB]"

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


ARCHIVE_EXTENSIONS = (
    ".zip",
    ".tar",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".txz",
)


def is_archive_file(path: str) -> bool:
    lower = path.lower()
    return any(lower.endswith(ext) for ext in ARCHIVE_EXTENSIONS)


def _format_entry_size(size_bytes: int) -> str:
    """Format bytes into a human-readable size string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    return f"{size_bytes / (1024 * 1024):.1f} MB"


def _inspect_archive(
    path: str,
    max_entries: int,
    start_line: int | None = None,
    end_line: int | None = None,
) -> ToolResult:
    import tarfile
    import zipfile

    lower = path.lower()
    dirs: set[str] = set()
    files: list[str] = []

    try:
        if lower.endswith(".zip"):
            with zipfile.ZipFile(path, "r") as zf:
                for info in zf.infolist():
                    name = info.filename
                    if not name or "__MACOSX" in name or os.path.basename(name).startswith("._"):
                        continue
                    if info.is_dir() or name.endswith("/"):
                        dirs.add(name.rstrip("/") + "/")
                    else:
                        files.append(f"{name} ({_format_entry_size(info.file_size)})")
        else:
            with tarfile.open(path, "r:*") as tf:
                for member in tf.getmembers():
                    name = member.name
                    if not name or "__MACOSX" in name or os.path.basename(name).startswith("._"):
                        continue
                    if member.isdir() or name.endswith("/"):
                        dirs.add(name.rstrip("/") + "/")
                    else:
                        files.append(f"{name} ({_format_entry_size(member.size)})")

        entries = sorted(dirs) + sorted(files)
        total_count = len(entries)
        if total_count == 0:
            content_str = f"[archive {path} | total 0]"
        elif start_line is not None and start_line > total_count:
            return ToolResult.error(
                "range",
                detail=f"start_line ({start_line}) exceeds entry count ({total_count}) in '{path}'. Total entries: {total_count} (range: 1..{total_count}).",
                name="read",
            )
        elif start_line is not None or end_line is not None:
            s = max(1, start_line) if start_line else 1
            e = min(total_count, end_line) if end_line else min(total_count, s + max_entries - 1)
            sliced = entries[s - 1 : e]
            body = "\n".join(sliced)
            content_str = f"[archive {path} | entries {s}..{e} of {total_count}]\n{body}"
        elif total_count > max_entries:
            body = "\n".join(entries[:max_entries])
            content_str = (
                f"[archive {path} | total {total_count} | truncated]\n"
                f"{body}\n"
                f"... [truncated | next read(path='{path}', start_line={max_entries + 1})]"
            )
        else:
            body = "\n".join(entries)
            content_str = f"[archive {path} | total {total_count}]\n{body}"

        return ToolResult.done(
            content=content_str,
            display="",
        )
    except Exception as e:
        return ToolResult.error("archive", detail=str(e), name=path)


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
                try:
                    raw_entries = sorted(os.listdir(path))
                    total_count = len(raw_entries)
                    tools = _tools_settings()
                    max_dir_entries = tools.max_dir_entries if tools else 60

                    normal_dirs, normal_files = [], []
                    hidden_dirs, hidden_files = [], []

                    for entry in raw_entries:
                        full_p = os.path.join(path, entry)
                        is_hidden = (
                            entry in DEFAULT_IGNORE_DIRS
                            or entry.startswith(".")
                            or entry.endswith(".egg-info")
                            or entry == "__pycache__"
                        )
                        if os.path.isdir(full_p):
                            try:
                                count = len(os.listdir(full_p))
                                label = f"{entry}/ ({count} items)" if count != 1 else f"{entry}/ (1 item)"
                            except Exception:
                                label = f"{entry}/"
                            if is_hidden:
                                hidden_dirs.append(label)
                            else:
                                normal_dirs.append(label)
                        else:
                            try:
                                sz = os.path.getsize(full_p)
                                label = f"{entry} ({_format_entry_size(sz)})"
                            except Exception:
                                label = entry
                            if is_hidden:
                                hidden_files.append(label)
                            else:
                                normal_files.append(label)

                    entries = normal_dirs + normal_files + hidden_dirs + hidden_files
                    if total_count == 0:
                        content_str = f"[dir {path} | total 0]"
                    elif start_line_int is not None and start_line_int > total_count:
                        return ToolResult.error(
                            "range",
                            detail=f"start_line ({start_line_int}) exceeds entry count ({total_count}) in '{path}'. Total entries: {total_count} (range: 1..{total_count}).",
                            name="read",
                        )
                    elif start_line_int is not None or end_line_int is not None:
                        s = max(1, start_line_int) if start_line_int else 1
                        e = min(total_count, end_line_int) if end_line_int else min(total_count, s + max_dir_entries - 1)
                        sliced = entries[s - 1 : e]
                        body = "\n".join(sliced)
                        content_str = f"[dir {path} | entries {s}..{e} of {total_count}]\n{body}"
                    elif len(entries) > max_dir_entries:
                        body = "\n".join(entries[:max_dir_entries])
                        content_str = (
                            f"[dir {path} | total {total_count} | truncated]\n"
                            f"{body}\n"
                            f"... [truncated | next read(path='{path}', start_line={max_dir_entries + 1})]"
                        )
                    else:
                        body = "\n".join(entries)
                        content_str = f"[dir {path} | total {total_count}]\n{body}"

                    return ToolResult.done(
                        content=content_str,
                        display="",
                    )
                except Exception as e:
                    return ToolResult.error("listing", detail=str(e), name=path)

            if is_archive_file(path):
                tools = _tools_settings()
                max_dir_entries = tools.max_dir_entries if tools else 60
                return _inspect_archive(path, max_dir_entries, start_line_int, end_line_int)

            try:
                file_size = os.path.getsize(path)
                limit = get_max_tool_payload_bytes()
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
        # Handle document formats (PDF, DOCX, etc.) via built-in converter
        if ext in DOC_EXTENSIONS:
            try:
                md_text = await run_cancellable(
                    convert_doc_to_markdown_sync,
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
                            import itertools

                            for _ in itertools.islice(f, s_line - 1):
                                pass
                        tools = _tools_settings()
                        window = tools.read_line_window if tools else DEFAULT_LINE_WINDOW
                        if e_line is not None:
                            # Read only up to the requested end line.
                            remaining = max(1, e_line - max(1, s_line or 1) + 1)
                        else:
                            remaining = window
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
                return ToolResult.error("execute", detail=f"read failed: {e}", name=path)

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
