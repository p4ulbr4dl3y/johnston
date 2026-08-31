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

Modal sizing: Textual cannot intrinsic-size a ``width: auto`` container that
holds an OptionList (measured at zero width during layout -> crash), so modal
dialogs keep their CSS ``width: 90%`` fallback and content-hugging is computed
here in Python via :func:`fit_modal_width` / :func:`apply_modal_fit`.
"""

from __future__ import annotations

import re
from typing import Any, Iterable

from widgets.utils.row_format import display_width

BREAKPOINT_BANNER = 52
BREAKPOINT_HINT = 60
BREAKPOINT_COMPACT = 75

# Classic terminal default used when no real size is available yet
# (pre-layout widgets, detached widgets, test doubles).
DEFAULT_TERMINAL_WIDTH = 80

# Modal dialog geometry: dialogs hug their content between a floor and a cap,
# and never claim more than MODAL_WIDTH_RATIO of the terminal width.
MODAL_MIN_WIDTH = 44
MODAL_COMPACT_MAX_WIDTH = 56
MODAL_MAX_WIDTH = 78
MODAL_MEDIUM_MAX_WIDTH = 86
MODAL_WIDE_MAX_WIDTH = 104
MODAL_WIDTH_RATIO = 0.9

# dialog padding (1 2) + border (2) + option row padding (0 1): 4 + 2 + 2
MODAL_CONTENT_GUTTER = 8

_MARKUP_RE = re.compile(r"[#*`]")


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


def resolve_screen_width(widget: Any) -> int:
    """Terminal width as seen from a widget inside a centered modal screen.

    Unlike :func:`resolve_width` this never trusts the widget's own size: a
    centered dialog's width is content-driven, not terminal-driven. Falls back
    through the real app to the ``_harness_app`` injection point, then
    ``DEFAULT_TERMINAL_WIDTH``. Never raises; returns a positive int.
    """
    sources = []
    try:
        sources.append(widget.app)
    except Exception:
        pass
    harness_app = getattr(widget, "_harness_app", None)
    if harness_app is not None:
        sources.append(harness_app)
    for source in sources:
        try:
            width = getattr(source.size, "width", None)
            if isinstance(width, int) and width > 0:
                return width
        except Exception:
            continue
    return DEFAULT_TERMINAL_WIDTH


def fit_modal_width(
    content_width: int,
    screen_width: int,
    *,
    min_width: int = MODAL_MIN_WIDTH,
    max_width: int = MODAL_MAX_WIDTH,
) -> int:
    """Ideal modal dialog width: hug content between floor and caps.

    Result is ``clamp(content_width, min_width, min(max_width, 90% screen))``
    so small dialogs stop stretching across the terminal while wide content
    still degrades exactly like the CSS ``width: 90%`` fallback on narrow
    terminals.
    """
    safe_content = max(0, content_width)
    ratio_cap = max(1, int(screen_width * MODAL_WIDTH_RATIO)) if screen_width > 0 else max_width
    cap = min(max_width, ratio_cap)
    return min(max(min_width, safe_content), cap)


def modal_content_width(
    options: Iterable[Any] | None = None,
    title: str = "",
    hint: str = "",
    esc_hint: str = "",
    *,
    extra: int = MODAL_CONTENT_GUTTER,
) -> int:
    """Rendered content width of a selection-style modal in terminal cells.

    Measures option rows (duck-typed ``prompt`` for Option instances), the
    title markdown with ``#``/``*``/backtick markup stripped, the hint
    line, and header with esc_hint; adds ``extra`` for dialog padding + border + option padding.
    """
    widest = 0
    for opt in options or ():
        text = getattr(opt, "prompt", opt)
        widest = max(widest, display_width(str(text)))
    for block in (title, hint, esc_hint):
        for line in str(block).splitlines():
            widest = max(widest, display_width(_MARKUP_RE.sub("", line).strip()))
    if title and esc_hint:
        header_w = display_width(_MARKUP_RE.sub("", title).strip()) + display_width(esc_hint) + 4
        widest = max(widest, header_w)
    return widest + extra


def apply_modal_fit(
    dialog: Any,
    content_width: int,
    *,
    min_width: int = MODAL_MIN_WIDTH,
    max_width: int = MODAL_MAX_WIDTH,
) -> int:
    """Set ``dialog`` width imperatively so it hugs its content.

    The CSS ``max-width`` cell cap stays in force (the fitted value never
    exceeds it); call again from ``on_resize`` to track terminal changes.
    Returns the applied width. Never raises.
    """
    try:
        width = fit_modal_width(
            content_width,
            resolve_screen_width(dialog),
            min_width=min_width,
            max_width=max_width,
        )
        dialog.styles.width = width
        return width
    except Exception:
        return 0
