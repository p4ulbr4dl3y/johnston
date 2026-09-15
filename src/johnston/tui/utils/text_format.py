"""Text formatting utilities for the Johnston TUI."""
from __future__ import annotations

from typing import Any, Iterable

from johnston.core.infrastructure.tasks.manage import format_duration as _format_duration
from johnston.core.infrastructure.tasks.output import (
    is_spinner_line as _is_spinner_line,
)
from johnston.core.infrastructure.tasks.output import (
    process_carriage_returns as _process_carriage_returns,
)
from johnston.core.infrastructure.tasks.output import (
    process_carriage_returns_lines as _process_carriage_returns_lines,
)
from johnston.core.infrastructure.tasks.output import (
    strip_ansi as _strip_ansi,
)
from johnston.core.tools.base import truncate_output as _truncate_output

__all__ = [
    "format_duration",
    "is_spinner_line",
    "process_carriage_returns",
    "process_carriage_returns_lines",
    "strip_ansi",
    "truncate_output",
]


def strip_ansi(text: str) -> str:
    """Strip ANSI escape sequences from text."""
    return _strip_ansi(text)


def truncate_output(*args: Any, **kwargs: Any) -> Any:
    """Truncate tool or command output for display."""
    return _truncate_output(*args, **kwargs)


def process_carriage_returns(text: str) -> str:
    """Process carriage returns in terminal output."""
    return _process_carriage_returns(text)


def process_carriage_returns_lines(
    lines: Iterable[str],
    tail: str = "",
    tail_is_spinner: bool = False,
) -> tuple[str, bool]:
    """Incremental variant of process_carriage_returns for streamed chunks."""
    return _process_carriage_returns_lines(lines, tail, tail_is_spinner)


def is_spinner_line(line: str) -> bool:
    """Check whether line is a standalone spinner character."""
    return _is_spinner_line(line)


def format_duration(seconds: float | int | None) -> str:
    """Format duration in seconds as concise string ('<0.1s', '4.2s', '14s', '1m 20s', '2h 15m')."""
    return _format_duration(seconds)
