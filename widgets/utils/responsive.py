"""Terminal-size adaptation primitives shared across widgets.

Textual 8.x has no media queries and clamps (rather than hides) widgets that
violate ``min-width``/``max-width``, so progressive disclosure and compact
layouts are implemented in render code against the breakpoints defined here.
This module is the single source of truth for those thresholds; do not inline
numeric literals in widget code.

Breakpoints are terminal columns, ordered narrow -> wide:

- ``BREAKPOINT_BANNER`` (52): below this the ASCII welcome banner is replaced
  by the plain wordmark (see ``widgets/presentation/widgets/chat_welcome.py``).
- ``BREAKPOINT_HINT`` (60): below this secondary keyboard hints collapse to
  their short form (diff footer, permission dialog).
- ``BREAKPOINT_COMPACT`` (75): below this status footers and diff headers
  switch to compact single-line rows (main footer, subagent footer/header).
"""

from __future__ import annotations

from typing import Any

BREAKPOINT_BANNER = 52
BREAKPOINT_HINT = 60
BREAKPOINT_COMPACT = 75

# Classic terminal default used when no real size is available yet
# (pre-layout widgets, detached widgets, test doubles).
DEFAULT_TERMINAL_WIDTH = 80


def resolve_width(widget: Any) -> int:
    """Best-effort visible width for ``widget`` in terminal cells.

    Preference order mirrors long-standing widget behavior:
    own mounted size -> app size (real ``app`` or the ``_harness_app``
    injection point honored by status-footer code) -> ``DEFAULT_TERMINAL_WIDTH``.
    Never raises; returns a positive int.
    """
    try:
        width = getattr(widget.size, "width", None)
        if isinstance(width, int) and width > 0:
            return width
    except Exception:
        pass
    apps = []
    try:
        apps.append(widget.app)
    except Exception:
        pass
    harness_app = getattr(widget, "_harness_app", None)
    if harness_app is not None:
        apps.append(harness_app)
    for app in apps:
        try:
            width = getattr(app.size, "width", None)
            if isinstance(width, int) and width > 0:
                return width
        except Exception:
            continue
    return DEFAULT_TERMINAL_WIDTH


def is_compact_width(width: Any, breakpoint: int = BREAKPOINT_COMPACT) -> bool:
    """True when ``width`` is a usable int below ``breakpoint``.

    Keeps the historical guard chain (int check + positive check) so callers
    passing raw/untrusted values behave exactly as before consolidation.
    """
    return isinstance(width, int) and width > 0 and width < breakpoint
