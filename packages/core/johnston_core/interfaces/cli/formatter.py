"""Formatting utilities for CLI output with plain and ANSI support."""
from __future__ import annotations

import os
import sys
from typing import Any, Sequence

RESET = "\033[0m"
BOLD = "\033[1m"
DIM = "\033[2m"
GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"


def supports_color() -> bool:
    """Check if the current terminal environment supports color output."""
    if os.environ.get("NO_COLOR") or os.environ.get("TERM") == "dumb":
        return False
    return sys.stdout.isatty()


def format_status(ok: bool, true_str: str = "✓", false_str: str = "✗", colorize: bool = True) -> str:
    """Format boolean status symbol with optional ANSI colors."""
    if colorize and supports_color():
        return f"{GREEN}{true_str}{RESET}" if ok else f"{RED}{false_str}{RESET}"
    return true_str if ok else false_str


def format_key_status(is_set: bool, colorize: bool = True) -> str:
    """Format configuration or API key status flag."""
    if colorize and supports_color():
        return f"{GREEN}[set]{RESET}" if is_set else f"{DIM}[unset]{RESET}"
    return "[set]" if is_set else "[unset]"


def truncate_str(text: str, max_len: int, ellipsis: str = "...") -> str:
    """Truncate text to max_len, appending ellipsis if truncated."""
    if max_len <= 0:
        return ""
    if len(text) <= max_len:
        return text
    if max_len <= len(ellipsis):
        return text[:max_len]
    return text[: max_len - len(ellipsis)] + ellipsis


def format_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[Any]],
    padding: int = 2,
    max_width: int | None = None,
    colorize_headers: bool = False,
) -> str:
    """Format rows into an aligned tabular string with headers, divider, and terminal-width constraints."""
    if not headers:
        return ""

    import shutil

    # Flatten newlines in cells so rows stay single-line
    str_rows: list[list[str]] = [
        [str(cell if cell is not None else "").replace("\r", " ").replace("\n", " ") for cell in row]
        for row in rows
    ]

    col_widths = [len(h) for h in headers]
    for row in str_rows:
        for idx, cell in enumerate(row):
            if idx < len(col_widths):
                col_widths[idx] = max(col_widths[idx], len(cell))
            else:
                col_widths.append(len(cell))

    num_cols = len(headers)
    total_padding = padding * max(0, num_cols - 1)

    target_max_width = max_width
    if target_max_width is None and sys.stdout.isatty():
        try:
            target_max_width = shutil.get_terminal_size().columns
        except Exception:
            target_max_width = None

    # Truncate widest columns if table exceeds max_width
    if target_max_width and target_max_width > (total_padding + num_cols * 4):
        available_content_width = target_max_width - total_padding
        current_content_width = sum(col_widths[:num_cols])

        while current_content_width > available_content_width:
            max_w = max(col_widths[:num_cols])
            widest_indices = [i for i in range(num_cols) if col_widths[i] == max_w]
            min_allowable = max(len(headers[widest_indices[0]]), 8)

            if max_w <= min_allowable:
                break

            for idx in widest_indices:
                col_widths[idx] = max_w - 1
                current_content_width -= 1
                if current_content_width <= available_content_width:
                    break

        # Apply truncations to row cells
        for row in str_rows:
            for idx in range(min(num_cols, len(row))):
                limit = col_widths[idx]
                if len(row[idx]) > limit:
                    row[idx] = truncate_str(row[idx], limit)

    pad = " " * padding
    if colorize_headers and supports_color():
        header_line = pad.join(f"{BOLD}{h.ljust(col_widths[i])}{RESET}" for i, h in enumerate(headers))
    else:
        header_line = pad.join(h.ljust(col_widths[i]) for i, h in enumerate(headers))

    divider_line = pad.join("-" * col_widths[i] for i in range(num_cols))

    data_lines = [
        pad.join(
            row[i].ljust(col_widths[i]) if i < len(row) else "".ljust(col_widths[i])
            for i in range(num_cols)
        )
        for row in str_rows
    ]

    return "\n".join([header_line, divider_line, *data_lines])


def format_kv(items: Sequence[tuple[str, Any]], indent: int = 2, col_width: int | None = None) -> str:
    """Format a list of key-value tuples with consistent alignment."""
    if not items:
        return ""
    actual_width = col_width or max(len(k) for k, _ in items)
    ind = " " * indent
    lines = [f"{ind}{k.ljust(actual_width)}: {v if v is not None else ''}" for k, v in items]
    return "\n".join(lines)
