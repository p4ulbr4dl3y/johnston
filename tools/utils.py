from tools.base import truncate_output

DEFAULT_LINE_WINDOW = 800


def format_line_pagination(
    lines: list[str],
    start_line: int | None = None,
    end_line: int | None = None,
    max_chars: int = 32000,
    hint: str = "",
    path: str = "",
) -> str:
    """Formats lines with 1-based line numbers and paginates by start_line/end_line range.

    Enforces a default max window of 800 lines per call.
    """
    total_lines = len(lines)
    if total_lines == 0:
        return f"=== 0 lines in {path} ===" if path else ""

    if start_line is not None:
        try:
            start_line = int(start_line)
        except (ValueError, TypeError):
            start_line = None

    if end_line is not None:
        try:
            end_line = int(end_line)
        except (ValueError, TypeError):
            end_line = None

    start = 1
    if start_line is not None:
        start = max(1, min(start_line, total_lines))

    if end_line is not None:
        end = max(start, min(end_line, total_lines))
    else:
        end = min(total_lines, start + DEFAULT_LINE_WINDOW - 1)

    selected = lines[start - 1 : end]
    output = []
    for i, line in enumerate(selected, start=start):
        output.append(f"{i:5d} | {line}")

    result_body = "\n".join(output)
    if len(result_body) > max_chars:
        result_body = truncate_output(result_body, max_chars=max_chars, hint=hint)

    header = f"=== Lines {start}-{end} of {total_lines}"
    if path:
        header += f" in {path}"
    header += " ==="

    if end < total_lines:
        next_start = end + 1
        next_end = min(total_lines, next_start + DEFAULT_LINE_WINDOW - 1)
        header += f"\n[Hint: File has {total_lines} lines. Use start_line={next_start} end_line={next_end} to read next chunk.]"

    return f"{header}\n{result_body}"
