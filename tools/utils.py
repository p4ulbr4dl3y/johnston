from tools.base import truncate_output


def format_line_pagination(
    lines: list[str],
    start_line: int | None = None,
    end_line: int | None = None,
    max_chars: int = 8000,
    hint: str = "Use start_line and end_line parameters to read specific chunks.",
) -> str:
    """Formats lines with 1-based line numbers and paginates by start_line/end_line range."""
    total_lines = len(lines)
    if total_lines == 0:
        return ""

    start = 1
    if start_line is not None:
        start = max(1, min(start_line, total_lines))

    end = total_lines
    if end_line is not None:
        end = max(start, min(end_line, total_lines))

    selected = lines[start - 1 : end]
    output = []
    for i, line in enumerate(selected, start=start):
        output.append(f"{i:5d} | {line}")

    result = "\n".join(output)
    if len(result) > max_chars:
        return truncate_output(result, max_chars=max_chars, hint=hint)
    return result
