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

from core.models_catalog import format_context_tokens

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
    from core.infrastructure.tasks.manage import format_duration as _canonical

    return _canonical(seconds)


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


def build_status_right_text(
    is_connected: bool,
    model_name: str,
    context_used: int,
    context_limit: int,
    cost_usd: float,
    total_tokens: int,
    txt: str,
    sep_compact: str,
) -> str:
    """Status-footer right cell: clamped context % beside cost (tokens when free).

    Shared by the status footer and subagent footer layouts.
    """
    if is_connected and bool(model_name):
        pct = (context_used / context_limit * 100) if context_limit > 0 else 0.0
        pct = min(100.0, max(0.0, pct))
        pct_str = "0%" if pct == 0 else f"{pct:.0f}%"
        cost_str = format_cost(cost_usd)
        right_val = cost_str if cost_usd > 0 else f"{format_context_tokens(total_tokens)}t"
        return f"[{txt}]{pct_str} ctx[/]{sep_compact}[{txt}]{right_val}[/]"
    return f"[{txt}]Run /connect[/]"


def build_env_left_parts(
    dir_text: str,
    branch: str | None,
    diff_text: str | None,
    sandbox_enabled: bool,
    execution_mode: str,
    txt: str,
    sep: str,
) -> str:
    """Status-footer left cell: ``dir • branch (+N/-M) • sandboxed • mode`` joined by sep.

    Shared by the status footer and subagent footer layouts.
    """
    row2_left_parts = [f"[{txt}]{dir_text}[/]"]
    if branch and diff_text:
        row2_left_parts.append(f"[{txt}]{branch} ({diff_text})[/]")
    elif branch:
        row2_left_parts.append(f"[{txt}]{branch}[/]")
    elif diff_text:
        row2_left_parts.append(f"[{txt}]({diff_text})[/]")
    if sandbox_enabled:
        row2_left_parts.append(f"[{txt}]sandboxed[/]")
    if execution_mode:
        row2_left_parts.append(f"[{txt}]{execution_mode}[/]")
    return sep.join(row2_left_parts)
