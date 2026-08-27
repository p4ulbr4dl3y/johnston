
from core.domain.defaults.errors import ToolResult
from tools.base import try_int

DEFAULT_LINE_WINDOW = 800

# Unified cap for any single file/web response fetched by a tool (read, web_fetch).
MAX_TOOL_PAYLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


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
        from core.infrastructure.runtime.xml_utils import escape_xml_attr

        p_attr = f' path="{escape_xml_attr(path)}"' if path else ""
        xml = f"<file{p_attr} lines=\"0\" total=\"0\"/>"
        return ToolResult.done(content=xml, display="")

    if start_line is not None:
        start_line_int = try_int(start_line)
        if start_line_int is not None and start_line_int > total_lines:
            path_str = f" in '{path}'" if path else ""
            if total_lines == 1:
                hint_str = "File has only 1 total line (e.g. minified JSON/log). Use start_line=1 and content_offset, or shell tools (jq/grep)."
            else:
                hint_str = f"File has {total_lines} total lines. Use start_line=1..{total_lines}."
            err_msg = (
                f"start_line ({start_line_int}) exceeds total file line count ({total_lines}){path_str}. "
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

    xml_lines = []
    current_len = 0
    actual_end = start - 1
    is_truncated = False

    for i in range(start, end + 1):
        idx = i - window_start
        if idx < 0 or idx >= len(lines):
            break
        raw_ln = lines[idx]
        formatted_xml = f"{i}|{raw_ln}"
        added_len = len(formatted_xml) + (1 if xml_lines else 0)
        if current_len + added_len > max_chars:
            if not xml_lines:
                xml_lines.append(formatted_xml[:max_chars])
                actual_end = i
            is_truncated = True
            break
        xml_lines.append(formatted_xml)
        current_len += added_len
        actual_end = i

    from core.infrastructure.runtime.xml_utils import escape_xml_attr

    attrs = []
    if path:
        attrs.append(f'path="{escape_xml_attr(path)}"')
    attrs.extend([f'start="{start}"', f'end="{actual_end}"', f'total="{total_lines}"'])
    if is_truncated or actual_end < end:
        attrs.append('truncated="1"')
    if converted_path:
        attrs.append(f'converted_log="{escape_xml_attr(converted_path)}"')

    xml_content = f"<file {' '.join(attrs)}>\n" + "\n".join(xml_lines) + "\n</file>"
    return ToolResult.done(content=xml_content, display="")
