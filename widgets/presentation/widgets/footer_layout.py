"""Layout calculations, separators, and path formatters for status footers."""
from __future__ import annotations

import os
import re

from rich.table import Table

from core.domain.defaults.config import THEME_MUTED, THEME_PRIMARY, THEME_SECONDARY, THEME_SUBTLE
from core.models_catalog import format_context_tokens
from widgets.mixins.stream_frame import SPINNER_FRAMES
from widgets.utils.row_format import ellipsize, format_cost

STATUS_SEP = f"  [{THEME_MUTED}]•[/]  "
STATUS_SEP_COMPACT = f" [{THEME_MUTED}]•[/] "


def get_theme_colors() -> tuple[str, str, str, str]:
    """Get active theme colors (primary, secondary, muted, subtle)."""
    try:
        from widgets.app.theme_manager import ThemeManager
        t = ThemeManager.get_instance().current_theme
        return t.primary, t.secondary, t.muted, t.subtle
    except Exception:
        return THEME_PRIMARY, THEME_SECONDARY, THEME_MUTED, THEME_SUBTLE


_COUNTER_RE = re.compile(r"^(\d+/\d+|\(\d+/\d+\)|\d+)$")


def format_modal_hint(raw_hint: str) -> str:
    """Format modal hotkey hint string with theme colors for keys, descriptions, and separators."""
    if not raw_hint:
        return ""
    if "[" in raw_hint and "]" in raw_hint and ("[/]" in raw_hint or "[/" in raw_hint):
        return raw_hint

    _, t_secondary, t_muted, _ = get_theme_colors()
    raw_segments = [s.strip() for s in raw_hint.split("•")]
    formatted_segments: list[str] = []

    for seg in raw_segments:
        if not seg:
            continue
        if ":" in seg:
            key, _, desc = seg.partition(":")
            key = key.strip()
            desc = desc.strip()
            formatted_segments.append(f"[{t_secondary}]{key}[/][{t_muted}]: {desc}[/]")
        elif _COUNTER_RE.match(seg):
            formatted_segments.append(f"[{t_muted}]{seg}[/]")
        else:
            formatted_segments.append(f"[{t_secondary}]{seg}[/]")

    sep = f" [{t_muted}]•[/] "
    return sep.join(formatted_segments)


def format_display_path(raw_path: str, max_length: int = 40) -> str:
    """Format directory path for footer display with worktree: prefix, ~/ for $HOME and middle truncation if long."""
    if not raw_path:
        return ""
    try:
        norm_path = os.path.abspath(os.path.expanduser(raw_path))
        home = os.path.abspath(os.path.expanduser("~"))
        home_real = os.path.realpath(home)
        norm_real = os.path.realpath(norm_path)

        # 1. Check if path is within worktrees directory
        wt_candidates: list[str] = []
        try:
            from core.infrastructure.platform.paths import WORKTREES_DIR

            if WORKTREES_DIR:
                wt_candidates.append(os.path.abspath(os.path.expanduser(WORKTREES_DIR)))
        except Exception:
            pass
        default_wt = os.path.abspath(os.path.expanduser("~/.johnston/worktrees"))
        if default_wt not in wt_candidates:
            wt_candidates.append(default_wt)

        display_path = None
        for wt in wt_candidates:
            wt_real = os.path.realpath(wt)
            if norm_path == wt or norm_real == wt_real:
                display_path = "worktree"
                break
            if norm_path.startswith(wt + os.sep):
                rel = os.path.relpath(norm_path, wt)
                display_path = f"worktree:{rel}"
                break
            if norm_real.startswith(wt_real + os.sep):
                rel = os.path.relpath(norm_real, wt_real)
                display_path = f"worktree:{rel}"
                break

        if display_path is None:
            if norm_path == home or norm_real == home_real:
                display_path = "~"
            elif norm_path.startswith(home + os.sep):
                rel = os.path.relpath(norm_path, home)
                display_path = f"~/{rel}"
            elif norm_real.startswith(home_real + os.sep):
                rel = os.path.relpath(norm_real, home_real)
                display_path = f"~/{rel}"
            else:
                display_path = norm_path

        if len(display_path) > max_length:
            if display_path.startswith("worktree:"):
                wt_suffix = display_path[len("worktree:") :]
                parts = wt_suffix.split(os.sep)
                if len(parts) > 1:
                    display_path = f"worktree:.../{parts[-1]}"
                if len(display_path) > max_length:
                    avail = max(6, max_length - len("worktree:"))
                    display_path = f"worktree:{ellipsize(parts[-1], avail)}"
            else:
                parts = display_path.split(os.sep)
                if len(parts) > 3:
                    display_path = f"{parts[0]}/{parts[1]}/.../{parts[-1]}"
                    if len(display_path) > max_length:
                        display_path = f"{parts[0]}/.../{parts[-1]}"
                elif len(parts) == 3:
                    display_path = f"{parts[0]}/.../{parts[-1]}"
        return display_path
    except Exception:
        return raw_path


def _build_subagent_grid(
    *,
    provider_display: str,
    clean_model: str,
    is_connected: bool,
    model_name: str,
    context_used: int,
    total_tokens: int,
    context_limit: int,
    context_window: str,
    cost_usd: float,
    thinking_effort: str,
    agent_role: str = "worker",
    is_generating: bool = False,
    spinner_idx: int = 0,
    directory: str = "",
    branch: str = "",
    git_diff_stats,
    is_compact: bool = False,
    sandbox_enabled: bool = True,
    execution_mode: str = "review",
    is_running: bool = False,
    from_tasks: bool = False,
) -> tuple[Table, list[tuple[str, str]]]:
    """Shared subagent-status table builder (2-line layout, with compact support)."""
    grid = Table.grid(expand=True)
    grid.add_column(justify="left")
    grid.add_column(justify="right")

    t_primary, t_secondary, t_muted, t_subtle = get_theme_colors()
    txt = t_secondary
    sep = f"  [{t_muted}]•[/]  "
    sep_compact = f" [{t_muted}]•[/] "
    arrow_sep = f" [{t_muted}]›[/] "

    role_str = (agent_role or "worker").capitalize()
    if is_generating:
        frame = SPINNER_FRAMES[spinner_idx % len(SPINNER_FRAMES)]
        role_formatted = f"{frame} {role_str}"
    else:
        role_formatted = role_str

    esc_label = "esc: back" if from_tasks else "esc: close"
    if is_compact:
        raw_hints = f"{esc_label} • ctrl+k" if is_running else esc_label
    else:
        raw_hints = f"{esc_label} • ctrl+k: kill" if is_running else esc_label
    row2_right = format_modal_hint(raw_hints)

    if is_compact:
        # Row 1 (Compact): Left [Role • Model] | Right [pct% ctx • $0.02 / tok]
        row1_left_parts = [f"[{txt}]{role_formatted}[/]"]
        if is_connected and clean_model and clean_model != "[Select model: /models]":
            row1_left_parts.append(f"[{txt}]{clean_model}[/]")
        row1_left = sep_compact.join(row1_left_parts)

        if is_connected and bool(model_name):
            pct = (context_used / context_limit * 100) if context_limit > 0 else 0.0
            pct = min(100.0, max(0.0, pct))
            pct_str = "0%" if pct == 0 else f"{pct:.0f}%"
            cost_str = format_cost(cost_usd)
            right_val = cost_str if cost_usd > 0 else f"{format_context_tokens(total_tokens)}t"
            row1_right = f"[{txt}]{pct_str} ctx[/]{sep_compact}[{txt}]{right_val}[/]"
        else:
            row1_right = f"[{txt}]Run /connect[/]"

        # Row 2 (Compact): Left [dir • branch (+N/-M) • sb:on • mode] | Right [esc • ctrl+k]
        dir_basename = os.path.basename(os.path.abspath(directory)) or directory
        row2_left_parts = [f"[{txt}]{dir_basename}[/]"]
        diff_text = git_diff_stats()
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
        row2_left = sep_compact.join(row2_left_parts)

        grid.add_row(row1_left, row1_right)
        grid.add_row(row2_left, row2_right)
        rows = [
            (row1_left, row1_right),
            (row2_left, row2_right),
        ]
        return grid, rows

    # Full mode
    # Row 1: Left [Role • Provider › Model (effort)] | Right [Context bar • tokens • cost]
    row1_left_parts = [f"[{txt}]{role_formatted}[/]"]
    if is_connected and provider_display and clean_model and clean_model != "[Select model: /models]":
        model_part = f"[{txt}]{provider_display}[/]{arrow_sep}[{txt}]{clean_model}[/]"
        if thinking_effort and thinking_effort != "auto":
            model_part += f" [{txt}]({thinking_effort})[/]"
        row1_left_parts.append(model_part)
    elif clean_model:
        row1_left_parts.append(f"[{txt}]{clean_model}[/]")
    row1_left = sep.join(row1_left_parts)

    if is_connected and model_name:
        pct = (context_used / context_limit * 100) if context_limit > 0 else 0.0
        pct = min(100.0, max(0.0, pct))
        bar_len = 8
        filled = int(round((pct / 100) * bar_len))
        empty = bar_len - filled
        bar_str = f"[{t_secondary}]{'█' * filled}[/][{t_muted}]{'░' * empty}[/]"
        cost_str = format_cost(cost_usd)
        tok_str = format_context_tokens(total_tokens)
        row1_right_parts = [
            f"[{t_muted}][[/]{bar_str}[{t_muted}]][/] [{txt}]{pct:.0f}% ({format_context_tokens(context_used)}/{context_window})[/]",
            f"[{txt}]{tok_str} tok[/]",
            f"[{txt}]{cost_str}[/]",
        ]
        row1_right = sep.join(row1_right_parts)
    else:
        row1_right = f"[{txt}]Run /connect to set up API key.[/]"
    grid.add_row(row1_left, row1_right)

    # Row 2: Left [directory • branch (+N/-M) • sandbox: on • mode] | Right [esc: close • ctrl+k: kill]
    dir_text = format_display_path(directory)
    row2_left_parts = [f"[{txt}]{dir_text}[/]"]
    diff_text = git_diff_stats()
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
    row2_left = sep.join(row2_left_parts)

    grid.add_row(row2_left, row2_right)

    rows = [
        (row1_left, row1_right),
        (row2_left, row2_right),
    ]
    return grid, rows
