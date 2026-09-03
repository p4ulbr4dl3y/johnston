import os
from typing import Any

from core.domain.defaults.errors import ToolResult
from tools.base import try_int

DEFAULT_LINE_WINDOW = 800

# Unified cap for any single file/web response fetched by a tool (read, web_fetch).
# The effective value reads tools.max_tool_payload_bytes from config; this
# constant is the fallback for direct callers.
MAX_TOOL_PAYLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


def get_max_tool_payload_bytes() -> int:
    """Return the configured tool payload cap (tools.max_tool_payload_bytes)."""
    try:
        from core.infrastructure.config.settings import get_settings

        return get_settings().tools.max_tool_payload_bytes
    except Exception:
        return MAX_TOOL_PAYLOAD_BYTES


def resolve_writable_path(ctx: Any, path_arg: Any) -> tuple[str, ToolResult | None]:
    """Resolves a path argument and rejects missing values or sandbox-blocked writes.

    Shared by create/edit so the path validation and sandbox permission check
    cannot drift between file-writing tools. Returns ``(resolved_path, None)`` on
    success, or ``("", error)`` when the path is empty or writes are not permitted
    by an active sandbox.
    """
    if not path_arg or not str(path_arg).strip():
        return "", ToolResult.error("params", name="path", detail="missing or empty")
    from tools.base import resolve_path

    path = resolve_path(str(path_arg), cwd=ctx.cwd)
    if getattr(ctx, "sandbox_enabled", False):
        from core.infrastructure.platform.sandbox import is_path_writable_in_sandbox

        if not is_path_writable_in_sandbox(path, cwd=ctx.cwd):
            return "", ToolResult.error("permission", f"sandbox restriction: write not permitted to '{path}' outside workspace")
    return path, None


def validate_file_for_edit(path: str) -> ToolResult | None:
    """Validate that a file exists, is not a directory, and does not exceed payload cap."""
    if not path or not os.path.exists(path):
        return ToolResult.error("not_found", name=path, detail="not found")
    if os.path.isdir(path):
        return ToolResult.error("is_directory", name=path, detail="is a directory")
    try:
        limit = get_max_tool_payload_bytes()
        if os.path.getsize(path) > limit:
            max_mb = limit // (1024 * 1024)
            return ToolResult.error("size_exceeded", name=path, detail=f"file exceeds maximum allowed size ({max_mb}MB)")
    except OSError:
        pass
    return None


def format_file_diff(old_content: str, new_content: str, path: str) -> str:
    """Generate git-style unified diff for file modifications."""
    from core.infrastructure.runtime.git_utils import make_git_diff

    return make_git_diff(old_content, new_content, fromfile=f"a/{path}", tofile=f"b/{path}")



def truncate_leading(text: str, max_chars: int) -> tuple[str, int]:
    """Clip ``text`` to its leading ``max_chars`` and report the shown line count.

    Shared leading-truncation step so callers only append their own footer text.
    Returns ``(truncated_text, shown_line_count)``.
    """
    truncated = text[:max_chars]
    shown_lines = truncated.count("\n") + (1 if truncated else 0)
    return truncated, shown_lines


def format_line_pagination(
    lines: list[str],
    start_line: int | None = None,
    end_line: int | None = None,
    max_chars: int = 32000,
    path: str = "",
    total_lines: int | None = None,
    window_start: int | None = None,
    converted_path: str | None = None,
) -> ToolResult:
    """Formats lines with token-efficient XML for LLM and human-friendly display for UI.

    Enforces a default max window of 800 lines per call and stops at clean line boundaries
    before exceeding max_chars.
    """
    total_lines = total_lines if total_lines is not None else len(lines)
    window_start = window_start if window_start is not None else 1
    effective_window = min(len(lines), DEFAULT_LINE_WINDOW)
    if total_lines == 0:
        p_info = f" | {path}" if path else ""
        return ToolResult.done(content=f"[empty file{p_info}]", display="")

    if start_line is not None:
        start_line_int = try_int(start_line)
        if start_line_int is not None and start_line_int > total_lines:
            path_str = f" in '{path}'" if path else ""
            if total_lines == 1:
                hint_str = "File has 1 line. Use content_offset."
            else:
                hint_str = f"File has {total_lines} lines (range: 1..{total_lines})."
            err_msg = (
                f"start_line ({start_line_int}) exceeds line count ({total_lines}){path_str}. "
                f"{hint_str}"
            )
            return ToolResult.error("range", detail=err_msg, name="read")
        start_line = start_line_int

    if end_line is not None:
        end_line = try_int(end_line)

    start = 1
    if start_line is not None:
        start = max(1, min(start_line, total_lines))

    if end_line is not None:
        end = max(start, min(end_line, total_lines))
        end = min(end, start + effective_window - 1)
    else:
        end = min(total_lines, start + effective_window - 1)

    out_lines = []
    current_len = 0
    actual_end = start - 1
    is_truncated = False

    for i in range(start, end + 1):
        idx = i - window_start
        if idx < 0 or idx >= len(lines):
            break
        raw_ln = lines[idx]
        formatted_line = f"{i}|{raw_ln}"
        added_len = len(formatted_line) + (1 if out_lines else 0)
        if current_len + added_len > max_chars:
            if not out_lines:
                out_lines.append(formatted_line[:max_chars])
                actual_end = i
            is_truncated = True
            break
        out_lines.append(formatted_line)
        current_len += added_len
        actual_end = i

    meta_parts = []
    if path:
        meta_parts.append(path)
    meta_parts.append(f"lines {start}..{actual_end} of {total_lines}")
    if is_truncated or actual_end < end:
        meta_parts.append("truncated")
    if converted_path:
        meta_parts.append(f"converted {converted_path}")

    header = f"[{' | '.join(meta_parts)}]"
    content_str = f"{header}\n" + "\n".join(out_lines) if out_lines else header
    return ToolResult.done(content=content_str, display="")
