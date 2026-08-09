
from tools.base import try_int

DEFAULT_LINE_WINDOW = 800


def format_line_pagination(
    lines: list[str],
    start_line: int | None = None,
    end_line: int | None = None,
    max_chars: int = 32000,
    path: str = "",
    hint: str = "",
) -> str:
    """Formats lines with 1-based line numbers and paginates by start_line/end_line range.

    Enforces a default max window of 800 lines per call and stops at clean line boundaries
    before exceeding max_chars.
    """
    total_lines = len(lines)
    if total_lines == 0:
        return f"=== 0 lines in {path} ===" if path else "=== 0 lines ==="

    if start_line is not None:
        start_line_int = try_int(start_line)
        if start_line_int is not None and start_line_int > total_lines:
            path_str = f" in '{path}'" if path else ""
            if total_lines == 1:
                hint_str = "File has only 1 total line (e.g. minified JSON/log). Re-run read tool with start_line=1 and content_offset, or use shell tools (jq/grep)."
            else:
                hint_str = f"File has {total_lines} total lines. Re-run read tool with start_line between 1 and {total_lines}"
            return (
                f"ERR: start_line ({start_line_int}) exceeds total file line count ({total_lines}){path_str}. "
                f"[Hint: {hint_str}]"
            )
        start_line = start_line_int

    if end_line is not None:
        end_line = try_int(end_line)

    start = 1
    if start_line is not None:
        start = max(1, min(start_line, total_lines))

    if end_line is not None:
        end = max(start, min(end_line, total_lines))
        end = min(end, start + DEFAULT_LINE_WINDOW - 1)
    else:
        end = min(total_lines, start + DEFAULT_LINE_WINDOW - 1)

    output = []
    current_len = 0
    actual_end = start - 1

    for i in range(start, end + 1):
        formatted_line = f"{i:5d} | {lines[i - 1]}"
        added_len = len(formatted_line) + (1 if output else 0)
        if current_len + added_len > max_chars:
            if not output:
                output.append(formatted_line[:max_chars])
                actual_end = i
            break
        output.append(formatted_line)
        current_len += added_len
        actual_end = i

    result_body = "\n".join(output)

    header = f"=== Lines {start}-{actual_end} of {total_lines}"
    if path:
        header += f" in {path}"
    header += " ==="

    if actual_end < total_lines:
        next_start = actual_end + 1
        next_end = min(total_lines, next_start + DEFAULT_LINE_WINDOW - 1)
        hint_text = f"\n[Hint: File has {total_lines} lines. Use start_line={next_start} end_line={next_end} to read next chunk.]"
        if actual_end < end:
            hint_text += f" [Warning: Output truncated at line {actual_end} before target line {end} due to character limit ({max_chars} chars).]"
        header += hint_text

    return f"{header}\n{result_body}"

