"""Right-aligned badge row formatting shared by modal OptionLists.

Single implementation of the "title ...spaces... [dim]badge[/]" row used by
the tasks/subagents, resume, rewind, MCP and diff-sidebar lists. All padding
math uses visible terminal-cell width (``rich.cells.cell_len``), so wide/CJK
characters keep the badge flush right instead of drifting.

Layout constants mirror ``app.tcss`` geometry:
- ``modal-dialog-medium``: max-width 86 - padding 2x2 - border 2 = 80 content.
- ``modal-dialog`` (default): max-width 78 - padding 2x2 - border 2 = 72.
- diff sidebar: CSS width 34 - border-right 1 - option padding 2x1 = 31.
"""
from typing import Any

from rich.cells import cell_len
from rich.markup import escape

MODAL_MEDIUM_ROW_WIDTH = 80
MODAL_DEFAULT_ROW_WIDTH = 72
DIFF_SIDEBAR_ROW_WIDTH = 31


def option_list_row_width(opt_list: Any, default: int) -> int:
    """Visible content width of a mounted OptionList for badge padding math.

    Falls back to ``default`` before layout (width 0), on unmounted widgets
    and on test doubles whose ``size.width`` is not an int.
    """
    try:
        width = opt_list.size.width
    except Exception:
        return default
    return width if isinstance(width, int) and width > 20 else default


def display_width(text: str) -> int:
    """Visible terminal-cell width of plain text (wide chars count 2)."""
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
    return f"{prefix}{escape(clean)}{' ' * pad}[dim #71717a]{badge}[/]"
