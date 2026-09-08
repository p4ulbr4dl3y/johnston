"""Interactive REPL package for Johnston CLI (`j`)."""
from __future__ import annotations

from typing import Optional


def start_repl(initial_prompt: Optional[str] = None) -> int:
    """Start the interactive agent REPL."""
    print("Johnston CLI interactive agent (REPL coming soon).")
    if initial_prompt:
        print(f"Initial prompt: {initial_prompt}")
    print("Run 'j --help' for available commands, or 'johnston' to start the full TUI.")
    return 0


__all__ = ["start_repl"]
