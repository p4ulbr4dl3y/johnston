"""Pure rendering helpers for the two-line status footer.

Module-level functions only: all state (spinner index, git results, theme
colors, widget width) is passed in explicitly so the widget keeps ownership
of timers, caches, and the grid application.
"""
from __future__ import annotations

import os

from johnston.tui.adapters import core_bridge
from johnston.tui.mixins.stream_frame import SPINNER_FRAMES
from johnston.tui.presentation.widgets.footer_layout import (
    format_display_path,
    get_theme_colors,
)
from johnston.tui.utils.row_format import (
    build_env_left_parts,
    build_status_right_text,
    display_width,
    ellipsize,
    format_cost,
)

format_context_tokens = core_bridge.format_context_tokens

__all__ = [
    "resolve_status_defaults",
    "render_compact_rows",
    "render_wide_rows",
]


def resolve_status_defaults(
    *,
    provider_key: str,
    provider_display: str | None,
    is_connected: bool | None,
    model_name: str,
    clean_model: str | None,
    agent_role: str,
    directory: str,
    app,
    catalog_mod=None,
    is_generating: bool,
    spinner_idx: int,
) -> dict:
    """Normalize partial ``update_status`` arguments into concrete render values.

    Mirrors the historical value-fallbacks: ``os.getcwd()`` directory,
    capitalized provider display, provider-manager connectivity probe,
    catalog model display name with the select-model placeholder, and the
    role display name with an optional spinner frame prefix.
    """
    if not directory:
        directory = os.getcwd()

    if provider_display is None:
        provider_display = provider_key.capitalize() if provider_key else ""
    if is_connected is None:
        pm = None
        try:
            pm = getattr(app, "pm", None)
        except Exception:
            pass
        is_connected = pm.is_provider_connected(provider_key) if (pm and provider_key) else bool(provider_key)
    if clean_model is None:
        client = getattr(app, "client", None) if app else None
        if client and hasattr(client, "get_model_info") and model_name:
            try:
                info = client.get_model_info(provider_key, model_name)
                clean_model = getattr(info, "display_name", "") or model_name
            except Exception:
                clean_model = ""
        elif catalog_mod and hasattr(catalog_mod, "get_model_display_name") and model_name:
            clean_model = catalog_mod.get_model_display_name(provider_key, model_name)
        if not clean_model:
            clean_model = "[Select model: /models]"
    from johnston.tui.adapters import core_bridge

    role_str = core_bridge.get_role_display_name(agent_role)
    if is_generating:
        frame = SPINNER_FRAMES[spinner_idx % len(SPINNER_FRAMES)]
        role_formatted = f"{frame} {role_str}"
    else:
        role_formatted = role_str

    return {
        "directory": directory,
        "provider_display": provider_display,
        "is_connected": is_connected,
        "clean_model": clean_model,
        "role_formatted": role_formatted,
    }


def render_compact_rows(
    *,
    width: int,
    role_formatted: str,
    provider_display: str,
    is_connected: bool,
    clean_model: str | None,
    model_name: str,
    context_used: int,
    context_limit: int,
    cost_usd: float,
    total_tokens: int,
    directory: str,
    branch: str,
    diff_text: str,
    sandbox_enabled: bool,
    execution_mode: str,
    subagents_active: int,
    active_bg_tasks: int,
    mcp_active: int,
    mcp_total: int,
    is_generating: bool,
) -> tuple[str, str, str, str]:
    """Compact (<75 cols) two-row footer grid content."""
    _, t_secondary, t_muted, _ = get_theme_colors()
    txt = t_secondary
    sep_compact = f" [{t_muted}]•[/] "

    row1_right = build_status_right_text(
        is_connected, model_name, context_used, context_limit, cost_usd, total_tokens, txt, sep_compact
    )

    # Row 1 (LLM): ⠋ Action • claude-3.7 (esc to interrupt)  <left> | <right> 45% ctx • $0.02
    row1_left_parts = [f"[{txt}]{role_formatted}[/]"]
    if is_connected and clean_model and clean_model != "[Select model: /models]":
        role_len = display_width(role_formatted) + 3
        hint_len = 20 if (is_generating and width >= 45) else 0
        right_len = 16
        max_model_len = max(10, width - role_len - hint_len - right_len - 3)
        disp_model = ellipsize(clean_model, max_model_len)
        model_str = f"[{txt}]{disp_model}[/]"
        if is_generating and width >= 45:
            model_str += f" [{t_muted}](esc to interrupt)[/]"
        row1_left_parts.append(model_str)
    elif is_generating and width >= 45:
        row1_left_parts.append(f"[{t_muted}](esc to interrupt)[/]")
    row1_left = sep_compact.join(row1_left_parts)

    # Row 2 (Env): johnston • main (+3/-1) • sb:on • mode  <left> | <right> ⚡ 2a • 1s
    dir_basename = format_display_path(directory, max_length=max(12, width // 3))
    row2_left_parts = [f"[{txt}]{dir_basename}[/]"]
    branch_disp = ellipsize(branch, max(10, width // 3)) if branch else ""
    if branch_disp and diff_text and width >= 50:
        row2_left_parts.append(f"[{txt}]{branch_disp} ({diff_text})[/]")
    elif branch_disp:
        row2_left_parts.append(f"[{txt}]{branch_disp}[/]")
    elif diff_text:
        row2_left_parts.append(f"[{txt}]({diff_text})[/]")
    if width >= 50:
        if sandbox_enabled:
            row2_left_parts.append(f"[{txt}]sandboxed[/]")
        if execution_mode:
            row2_left_parts.append(f"[{txt}]{execution_mode}[/]")
    row2_left = sep_compact.join(row2_left_parts)

    task_parts = []
    if subagents_active > 0:
        task_parts.append(f"[{txt}]{subagents_active}a[/]")
    if active_bg_tasks > 0:
        task_parts.append(f"[{txt}]{active_bg_tasks}s[/]")
    if mcp_total > 0:
        task_parts.append(f"[{txt}]{mcp_active}mcp[/]")
    row2_right = f"[{txt}]⚡[/] {sep_compact.join(task_parts)}" if task_parts else ""

    return row1_left, row1_right, row2_left, row2_right


def render_wide_rows(
    *,
    width: int,
    role_formatted: str,
    provider_display: str,
    is_connected: bool,
    clean_model: str | None,
    model_name: str,
    thinking_effort: str,
    context_used: int,
    context_limit: int,
    context_window: str,
    total_tokens: int,
    cost_usd: float,
    directory: str,
    branch: str,
    diff_text: str,
    sandbox_enabled: bool,
    execution_mode: str,
    subagents_active: int,
    active_bg_tasks: int,
    mcp_active: int,
    mcp_total: int,
    is_generating: bool,
) -> tuple[str, str, str, str]:
    """Wide (>=75 cols) two-row footer grid content."""
    _, t_secondary, t_muted, _ = get_theme_colors()
    txt = t_secondary
    sep = f"  [{t_muted}]•[/]  "
    arrow_sep = f" [{t_muted}]›[/] "

    # Row 1 (LLM): ⠋ Action • OpenRouter › claude-3.7 (high) (esc to interrupt)  <left> | <right> [████░░░░] 45% (58k/128k) • 12.3k tok • $0.02
    row1_left_parts = [f"[{txt}]{role_formatted}[/]"]
    if is_connected and provider_display and clean_model and clean_model != "[Select model: /models]":
        model_part = f"[{txt}]{provider_display}[/]{arrow_sep}[{txt}]{clean_model}[/]"
        if thinking_effort and thinking_effort != "auto":
            model_part += f" [{txt}]({thinking_effort})[/]"
        if is_generating:
            model_part += f" [{t_muted}](esc to interrupt)[/]"
        row1_left_parts.append(model_part)
    elif is_generating:
        row1_left_parts.append(f"[{t_muted}](esc to interrupt)[/]")
    row1_left = sep.join(row1_left_parts)

    if is_connected and bool(model_name):
        ctx_val = context_used
        pct = (ctx_val / context_limit * 100) if context_limit > 0 else 0.0
        pct = min(100.0, max(0.0, pct))
        bar_len = 8
        filled = int(round((pct / 100) * bar_len))
        empty = bar_len - filled
        bar_str = f"[{t_secondary}]{'█' * filled}[/][{t_muted}]{'░' * empty}[/]"
        used_formatted = format_context_tokens(ctx_val)
        cost_str = format_cost(cost_usd)
        tok_str = format_context_tokens(total_tokens)
        row1_right_parts = [
            f"[{t_muted}][[/]{bar_str}[{t_muted}]][/] [{txt}]{pct:.0f}% ({used_formatted}/{context_window})[/]",
            f"[{txt}]{tok_str} tok[/]",
            f"[{txt}]{cost_str}[/]",
        ]
        row1_right = sep.join(row1_right_parts)
    else:
        row1_right = f"[{txt}]Run /connect to set up API key.[/]"

    # Row 2 (Env): ~/repo/johnston • main (+12/-3) • sandbox: on • mode  <left> | <right> ⚡ 2 agents • 1 shell • 4 MCP
    max_path_len = min(50, max(25, width // 3))
    dir_text = format_display_path(directory, max_length=max_path_len)
    row2_left = build_env_left_parts(dir_text, branch, diff_text, sandbox_enabled, execution_mode, txt, sep)

    service_parts = []
    if subagents_active > 0:
        service_parts.append(
            f"[{txt}]{subagents_active} agent[/]" if subagents_active == 1 else f"[{txt}]{subagents_active} agents[/]"
        )
    if active_bg_tasks > 0:
        service_parts.append(f"[{txt}]{active_bg_tasks} shell[/]")
    if mcp_total > 0:
        mcp_str = f"{mcp_active} MCP" if mcp_active == mcp_total else f"{mcp_active}/{mcp_total} MCP"
        service_parts.append(f"[{txt}]{mcp_str}[/]")

    if service_parts:
        row2_right = f"[{txt}]⚡[/] {sep.join(service_parts)}"
    else:
        row2_right = ""

    return row1_left, row1_right, row2_left, row2_right
