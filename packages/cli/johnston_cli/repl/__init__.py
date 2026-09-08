"""REPL package placeholder for future implementation."""
from __future__ import annotations

import sys
from typing import Any, Optional


def start_repl(initial_prompt: Optional[str] = None, args: Any = None) -> int:
    """Placeholder for future REPL implementation."""
    sys.stdout.write(
        "Johnston REPL is under development.\n"
        "To use Johnston, run:\n"
        "  johnston          - Launch interactive TUI\n"
        "  j \"prompt\"        - Run headless task\n"
    )
    sys.stdout.flush()
    return 0


__all__ = ["start_repl"]

