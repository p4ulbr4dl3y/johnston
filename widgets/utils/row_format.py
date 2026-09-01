"""Right-aligned badge row formatting shared by modal OptionLists.

Single implementation of the "title ...spaces... [dim]badge[/]" row used by
the tasks/subagents, resume, rewind, MCP and diff-sidebar lists. All padding
math uses visible terminal-cell width (``rich.cells.cell_len``), so wide/CJK
characters keep the badge flush right instead of drifting.

Layout constants mirror ``app.tcss`` geometry (modal OptionList options render
with ``padding: 0`` so badges sit flush against the dialog boundary):
- ``modal-dialog-wide``: max-width 104 - dialog padding 2x2 - border 2 = 98.
- ``modal-dialog-medium``: max-width 86 - dialog padding 2x2 - border 2 = 80.
- ``modal-dialog`` (default): max-width 78 - dialog padding 2x2 - border 2 = 72.
- diff sidebar: CSS width 32 - border-right 1 = 31.
"""
import time
from typing import Any

from rich.cells import cell_len
from rich.markup import escape
from rich.text import Text

MODAL_WIDE_ROW_WIDTH = 98
MODAL_MEDIUM_ROW_WIDTH = 80
MODAL_DEFAULT_ROW_WIDTH = 72
DIFF_SIDEBAR_ROW_WIDTH = 31


def format_relative_time(ts: float | int | None, now: float | int | None = None) -> str:
    """Format timestamp as concise relative time ('just now', '5m ago', '2h ago', '3d ago', etc.)."""
    if ts is None:
        return ""
    try:
        ts_float = float(ts)
    except (ValueError, TypeError):
        return ""
    if ts_float <= 0:
        return ""

    cur = float(now) if now is not None else time.time()
    diff = int(cur - ts_float)
    if diff < 60:
        return "just now"
    if diff < 3600:
        return f"{diff // 60}m ago"
    if diff < 86400:
        return f"{diff // 3600}h ago"
    if diff < 604800:
        return f"{diff // 86400}d ago"
    if diff < 2592000:
        return f"{diff // 604800}w ago"
    if diff < 31536000:
        return f"{diff // 2592000}mo ago"
    return f"{diff // 31536000}y ago"


def format_duration(seconds: float | int | None) -> str:
    """Format duration in seconds as concise string ('<0.1s', '4.2s', '14s', '1m 20s', '2h 15m')."""
    if seconds is None:
        return ""
    try:
        sec = float(seconds)
    except (ValueError, TypeError):
        return ""
    if sec < 0:
        sec = 0.0
    if sec < 60:
        if sec < 0.1:
            return "<0.1s" if sec > 0 else "0s"
        if sec < 10:
            return f"{sec:.1f}s"
        return f"{int(sec)}s"
    if sec < 3600:
        minutes = int(sec // 60)
        secs = int(sec % 60)
        return f"{minutes}m {secs:02d}s"
    hours = int(sec // 3600)
    mins = int((sec % 3600) // 60)
    return f"{hours}h {mins:02d}m"


def format_cost(cost_usd: float | int | None) -> str:
    """Format cost in USD as concise string ('$0', '<$0.01', '$0.05', '$1.20')."""
    if cost_usd is None:
        return "$0"
    try:
        val = float(cost_usd)
    except (ValueError, TypeError):
        return "$0"
    if val <= 0:
        return "$0"
    if val < 0.01:
        return "<$0.01"
    return f"${val:.2f}"



def option_list_row_width(opt_list: Any, default: int) -> int:
    """Visible content width of a mounted OptionList for badge padding math.

    When unmounted or before layout, clamps ``default`` against
    the screen width so narrow terminals don't overflow even on initial draw.
    """
    try:
        width = opt_list.size.width
        if isinstance(width, int) and width > 0:
            return max(20, width)
    except Exception:
        pass

    # Unmounted / pre-layout fallback: clamp default to terminal width
    try:
        from widgets.utils.responsive import MODAL_CONTENT_GUTTER, MODAL_WIDTH_RATIO, resolve_screen_width

        screen_w = resolve_screen_width(opt_list)
        if screen_w > 0:
            cap = int(screen_w * MODAL_WIDTH_RATIO) - MODAL_CONTENT_GUTTER
            return max(20, min(default, cap))
    except Exception:
        pass
    return default


def display_width(text: str) -> int:
    """Visible terminal-cell width of text, stripping rich markup if present."""
    if "[" in text and "]" in text:
        try:
            return cell_len(Text.from_markup(text).plain)
        except Exception:
            return cell_len(text)
    return cell_len(text)


def ellipsize(text: str, max_width: int) -> str:
    """Clip text to at most ``max_width`` cells ending with a trailing ``...``."""
    if display_width(text) <= max_width:
        return text
    budget = max(0, max_width - 3)
    out: list[str] = []
    used = 0
    for ch in text:
        w = display_width(ch)
        if used + w > budget:
            break
        out.append(ch)
        used += w
    return "".join(out) + "..."


def format_badge_row(
    title: str,
    badge: str = "",
    target_width: int = MODAL_MEDIUM_ROW_WIDTH,
    prefix: str = "",
    min_gap: int = 2,
    min_title: int = 10,
) -> str:
    """Format an option row as ``prefix title ...spaces... [dim]badge[/]``.

    Title is whitespace-collapsed and truncated (cell-aware) to reserve badge
    space; the title is markup-escaped while the badge is passed through so it
    can carry its own style. An empty badge yields a plain prefix+title row.
    """
    clean = " ".join(str(title).replace("\n", " ").replace("\r", " ").split())
    if not badge:
        return f"{prefix}{escape(clean)}"
    max_title = max(min_title, target_width - display_width(prefix) - display_width(badge) - min_gap)
    if display_width(clean) > max_title:
        clean = ellipsize(clean, max_title)
    pad = max(min_gap, target_width - display_width(prefix) - display_width(clean) - display_width(badge))
    return f"{prefix}{escape(clean)}{' ' * pad}[dim]{badge}[/]"


def fit_row(
    left: str | Text,
    right: str | Text = "",
    width: int = 80,
    gap: int = 2,
    min_left: int = 8,
) -> Text:
    """Compose one ``left …spaces… right`` row guaranteed to fit ``width`` cells.

    Rich's ``Table.grid(expand=True)`` splits the terminal equally between its
    columns, so a long left cell wraps and is clipped by fixed-height footers
    (losing the tail silently). Building the row as a single :class:`Text`
    lets the left cell use the full width minus the right cell, and degrades
    with an ellipsis instead of dropping content.
    """
    left_t = left.copy() if isinstance(left, Text) else Text.from_markup(str(left))
    right_t = right.copy() if isinstance(right, Text) else Text.from_markup(str(right))
    safe_width = max(gap + min_left, int(width))
    left_w, right_w = cell_len(left_t.plain), cell_len(right_t.plain)

    if left_w + right_w + gap > safe_width:
        left_budget = safe_width - right_w - gap
        if left_budget < min_left and right_w:
            # Left would be squeezed to nothing: give back space from the right.
            right_budget = safe_width - left_w - gap
            if right_budget >= 1:
                right_t.truncate(right_budget, overflow="ellipsis", pad=False)
                right_w = cell_len(right_t.plain)
            else:
                right_t = Text("")
                right_w = 0
            left_budget = safe_width - right_w - gap
        if left_w > max(1, left_budget):
            left_t.truncate(max(1, left_budget), overflow="ellipsis", pad=False)
            left_w = cell_len(left_t.plain)

    pad = max(gap, safe_width - left_w - right_w)
    row = left_t.copy()
    row.append(" " * pad)
    row.append_text(right_t)
    return row


def compose_rows(rows: list[tuple[str, str]] | list[tuple[str]], width: int, gap: int = 2) -> Text:
    """Stack fitted rows into a single multi-line :class:`Text` renderable."""
    out = Text()
    for index, row in enumerate(rows):
        if index:
            out.append("\n")
        right = row[1] if len(row) > 1 else ""
        out.append_text(fit_row(row[0], right, width, gap=gap))
    return out
