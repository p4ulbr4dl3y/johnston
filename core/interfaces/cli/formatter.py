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


def format_table(headers: Sequence[str], rows: Sequence[Sequence[Any]], padding: int = 2) -> str:
    """Format rows into an aligned tabular string with headers and divider."""
    if not headers:
        return ""

    str_rows: list[list[str]] = [[str(cell if cell is not None else "") for cell in row] for row in rows]
    col_widths = [len(h) for h in headers]
    for row in str_rows:
        for idx, cell in enumerate(row):
            if idx < len(col_widths):
                col_widths[idx] = max(col_widths[idx], len(cell))
            else:
                col_widths.append(len(cell))

    pad = " " * padding
    header_line = pad.join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    divider_line = pad.join("-" * col_widths[i] for i in range(len(headers)))

    data_lines = [pad.join(row[i].ljust(col_widths[i]) if i < len(row) else "".ljust(col_widths[i])
                           for i in range(len(headers))) for row in str_rows]

    return "\n".join([header_line, divider_line, *data_lines])


def format_kv(items: Sequence[tuple[str, Any]], indent: int = 2, col_width: int | None = None) -> str:
    """Format a list of key-value tuples with consistent alignment."""
    if not items:
        return ""
    actual_width = col_width or max(len(k) for k, _ in items)
    ind = " " * indent
    lines = [f"{ind}{k.ljust(actual_width)}: {v if v is not None else ''}" for k, v in items]
    return "\n".join(lines)
