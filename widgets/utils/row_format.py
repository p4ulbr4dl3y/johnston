"""Right-aligned badge row formatting shared by modal OptionLists.

Single implementation of the "title ...spaces... [dim]badge[/]" row used by
the tasks/subagents, resume, rewind, MCP and diff-sidebar lists. All padding
math uses visible terminal-cell width (``rich.cells.cell_len``), so wide/CJK
characters keep the badge flush right instead of drifting.

Layout constants mirror ``app.tcss`` geometry (OptionList options render
with Textual's default ``padding: 0 1``, so 2 columns are subtracted):
- ``modal-dialog-medium``: max-width 86 - dialog padding 2x2 - border 2
  - option padding 2x1 = 78.
- ``modal-dialog`` (default): max-width 78 - dialog padding 2x2 - border 2
  - option padding 2x1 = 70.
- diff sidebar: CSS width 34 - border-right 1 - option padding 2x1 = 31.
"""
from typing import Any

from rich.cells import cell_len
from rich.markup import escape
from rich.text import Text

MODAL_WIDE_ROW_WIDTH = 96
MODAL_MEDIUM_ROW_WIDTH = 78
MODAL_DEFAULT_ROW_WIDTH = 70
DIFF_SIDEBAR_ROW_WIDTH = 31


def option_list_row_width(opt_list: Any, default: int) -> int:
    """Visible content width of a mounted OptionList for badge padding math.

    Subtracts Textual's OptionList option padding (0 1 -> 2 cells) from the
    widget width. When unmounted or before layout, clamps ``default`` against
    the screen width so narrow terminals don't overflow even on initial draw.
    """
    try:
        width = opt_list.size.width
        if isinstance(width, int) and width > 20:
            return max(20, width - 2)
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
    return f"{prefix}{escape(clean)}{' ' * pad}[dim #71717a]{badge}[/]"
