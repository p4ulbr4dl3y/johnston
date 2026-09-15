"""Terminal palette detection and adaptation utilities for the Johnston TUI."""
from __future__ import annotations

from typing import Any

__all__ = [
    "compute_adaptive_palette",
    "query_terminal_palette",
]


def query_terminal_palette(*args: Any, **kwargs: Any) -> Any:
    """Query the terminal color palette."""
    from johnston.core.infrastructure.platform.terminal_theme import (
        query_terminal_palette as _f,
    )

    return _f(*args, **kwargs)


def compute_adaptive_palette(bg: str | None = None, fg: str | None = None) -> Any:
    """Compute an adapted terminal palette based on background and foreground colors."""
    from johnston.core.infrastructure.platform.terminal_theme import (
        compute_adaptive_palette as _f,
    )

    return _f(bg, fg)
