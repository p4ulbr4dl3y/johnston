"""Two-line status footer below chat and re-exports for subagent footer/headers."""
from __future__ import annotations

import os

from rich.table import Table
from textual.widgets import Static

from core.domain.defaults.config import THEME_MUTED, THEME_PRIMARY, THEME_SECONDARY, THEME_SUBTLE
from core.models_catalog import catalog, format_context_tokens
from widgets.git_metrics_mixin import GitMetricsMixin
from widgets.mixins.resize_debounce import ResizeDebounceMixin
from widgets.mixins.stream_frame import SPINNER_FRAMES, StreamFrameMixin
from widgets.presentation.widgets.footer_layout import (
    STATUS_SEP,
    STATUS_SEP_COMPACT,
    _build_subagent_grid,
    format_display_path,
)
from widgets.presentation.widgets.subagent_footer import (
    SubagentHeader,
    SubagentStatusFooter,
)
from widgets.utils.responsive import is_compact_width, resolve_width
from widgets.utils.row_format import display_width, ellipsize

__all__ = [
    "STATUS_SEP",
    "STATUS_SEP_COMPACT",
    "StatusFooter",
    "SubagentHeader",
    "SubagentStatusFooter",
    "_build_subagent_grid",
    "format_display_path",
]


class StatusFooter(ResizeDebounceMixin, GitMetricsMixin, StreamFrameMixin, Static):
    """Two-line status footer below chat."""

    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.is_generating: bool = False
        self._spinner_idx: int = 0
        self._spinner_timer = None
        self._mcp_poll_timer = None

    def set_generating(self, generating: bool) -> None:
        if self.is_generating == generating:
            return
        self.is_generating = generating
        if generating:
            if not self._spinner_timer:
                self._spinner_timer = self.set_interval(0.2, self._spin)
        else:
            if self._spinner_timer:
                self._spinner_timer.stop()
                self._spinner_timer = None
            self._spinner_idx = 0
        self.refresh_footer()

    def _spin(self) -> None:
        self._spinner_idx = (self._spinner_idx + 1) % len(SPINNER_FRAMES)
        if hasattr(self, "_last_status_args"):
            self._render_stream_frame()
        else:
            self.refresh_footer()

    def on_mount(self) -> None:
        self.refresh_footer()
        try:
            from core.infrastructure.mcp import get_mcp_manager

            mgr = get_mcp_manager()
            if mgr and hasattr(mgr, "add_listener"):
                mgr.add_listener(self._on_mcp_event)
        except Exception:
            pass

    def on_unmount(self) -> None:
        try:
            from core.infrastructure.mcp import get_mcp_manager

            mgr = get_mcp_manager()
            if mgr and hasattr(mgr, "remove_listener"):
                mgr.remove_listener(self._on_mcp_event)
        except Exception:
            pass
        if getattr(self, "_spinner_timer", None):
            try:
                self._spinner_timer.stop()
            except Exception:
                pass
            self._spinner_timer = None
        if getattr(self, "_mcp_poll_timer", None):
            try:
                self._mcp_poll_timer.stop()
            except Exception:
                pass
            self._mcp_poll_timer = None
        self.cancel_resize_timer()

    def _on_mcp_event(self, _event: str = "") -> None:
        """Reactive MCP event handler: triggers footer update when MCP state changes."""
        if hasattr(self, "_st_cache_time"):
            self._st_cache_time = 0.0
        try:
            from widgets.app.status_state import refresh_footer_cache

            app = getattr(self, "_app", None) or (self.app if hasattr(self, "app") and self.is_mounted else None)
            if app:
                import asyncio

                try:
                    asyncio.get_running_loop().create_task(refresh_footer_cache(app, self))
                    return
                except RuntimeError:
                    pass
            self.refresh_footer()
        except Exception:
            self.refresh_footer()

    def _apply_two_row_grid(self, row1_left, row1_right, row2_left, row2_right) -> None:
        """Render the two-line footer grid and cache its rows for spin re-draws."""
        grid = Table.grid(expand=True)
        grid.add_column(justify="left")
        grid.add_column(justify="right")
        grid.add_row(row1_left, row1_right)
        grid.add_row(row2_left, row2_right)
        self._last_grid_rows = [
            (row1_left, row1_right),
            (row2_left, row2_right),
        ]
        self.update(grid)

    def refresh_footer(self) -> None:
        if not self.app:
            return
        try:
            from widgets.app.status_state import build_status_kwargs

            kwargs = build_status_kwargs(self.app, widget=self)
            self._last_status_args = kwargs
            self.update_status(**kwargs)
        except Exception:
            self.update_status(provider_key="default")

    def update_status(
        self,
        provider_key: str,
        provider_display: str | None = None,
        is_connected: bool | None = None,
        model_name: str = "",
        clean_model: str | None = None,
        agent_role: str = "action",
        directory: str = "",
        active_bg_tasks: int = 0,
        subagents_active: int = 0,
        subagents_total: int = 0,
        context_used: int = 0,
        total_tokens: int = 0,
        context_window: str = "128k",
        context_limit: int = 128000,
        cost_usd: float = 0.0,
        thinking_effort: str = "auto",
        skills_visible: int = 0,
        skills_total: int = 0,
        mcp_active: int = 0,
        mcp_total: int = 0,
        attachments_count: int = 0,
        sandbox_enabled: bool = False,
        execution_mode: str = "review",
    ) -> None:
        if not directory:
            directory = os.getcwd()

        if provider_display is None:
            provider_display = provider_key.capitalize() if provider_key else ""
        if is_connected is None:
            pm = None
            try:
                pm = getattr(self.app, "pm", None)
            except Exception:
                pass
            is_connected = pm.is_provider_connected(provider_key) if (pm and provider_key) else bool(provider_key)
        if clean_model is None:
            clean_model = catalog.get_model_display_name(provider_key, model_name)
            if not clean_model:
                clean_model = "[Select model: /models]"
        role_str = agent_role.capitalize()
        if self.is_generating:
            frame = SPINNER_FRAMES[self._spinner_idx % len(SPINNER_FRAMES)]
            role_formatted = f"{frame} {role_str}"
        else:
            role_formatted = role_str

        width = resolve_width(self)
        is_compact = is_compact_width(width)

        if is_compact:
            branch = self._git_branch(cwd=directory)
            diff_text = self._git_diff_stats(cwd=directory)

            if is_connected and bool(model_name):
                pct = (context_used / context_limit * 100) if context_limit > 0 else 0.0
                pct = min(100.0, max(0.0, pct))
                pct_str = "0%" if pct == 0 else f"{pct:.0f}%"
                cost_str = "$0" if cost_usd == 0 else f"${cost_usd:.2f}"
                right_val = cost_str if cost_usd > 0 else f"{format_context_tokens(total_tokens)}t"
                row1_right = f"[{THEME_SECONDARY}]{pct_str} ctx[/]{STATUS_SEP_COMPACT}[{THEME_SECONDARY}]{right_val}[/]"
            else:
                row1_right = f"[{THEME_SUBTLE}]Run /connect[/{THEME_SUBTLE}]"

            # Row 1 (LLM): ⠋ Action • claude-3.7  <left> | <right> 45% ctx • $0.02
            row1_left_parts = [f"[bold {THEME_PRIMARY}]{role_formatted}[/]"]
            if is_connected and clean_model and clean_model != "[Select model: /models]":
                role_len = display_width(role_formatted) + 3
                right_len = 16
                max_model_len = max(10, width - role_len - right_len - 3)
                disp_model = ellipsize(clean_model, max_model_len)
                row1_left_parts.append(f"[{THEME_SECONDARY}]{disp_model}[/]")
            row1_left = STATUS_SEP_COMPACT.join(row1_left_parts)

            # Row 2 (Env): johnston • main (+3/-1) • sb:on • mode  <left> | <right> ⚡ 2a • 1s
            dir_raw = os.path.basename(os.path.abspath(directory)) or directory
            dir_basename = ellipsize(dir_raw, max(12, width // 3))
            row2_left_parts = [f"[{THEME_SECONDARY}]{dir_basename}[/]"]
            branch_disp = ellipsize(branch, max(10, width // 3)) if branch else ""
            if branch_disp and diff_text and width >= 50:
                row2_left_parts.append(f"[{THEME_PRIMARY}]{branch_disp}[/] [{THEME_SECONDARY}]({diff_text})[/]")
            elif branch_disp:
                row2_left_parts.append(f"[{THEME_PRIMARY}]{branch_disp}[/]")
            elif diff_text:
                row2_left_parts.append(f"[{THEME_SECONDARY}]({diff_text})[/]")
            if width >= 50:
                row2_left_parts.append(f"[{THEME_PRIMARY}]sb:on[/]" if sandbox_enabled else f"[{THEME_MUTED}]sb:off[/]")
                if execution_mode:
                    row2_left_parts.append(f"[{THEME_SECONDARY}]{execution_mode}[/]")
            row2_left = STATUS_SEP_COMPACT.join(row2_left_parts)

            task_parts = []
            if subagents_active > 0:
                task_parts.append(f"[{THEME_SECONDARY}]{subagents_active}a[/]")
            if active_bg_tasks > 0:
                task_parts.append(f"[{THEME_SECONDARY}]{active_bg_tasks}s[/]")
            if mcp_total > 0:
                task_parts.append(f"[{THEME_SECONDARY}]{mcp_active}mcp[/]")
            row2_right = f"[{THEME_SECONDARY}]⚡[/] {STATUS_SEP_COMPACT.join(task_parts)}" if task_parts else ""

            self._apply_two_row_grid(row1_left, row1_right, row2_left, row2_right)
        else:
            branch = self._git_branch(cwd=directory)
            diff_text = self._git_diff_stats(cwd=directory)

            # Row 1 (LLM): ⠋ Action • OpenRouter › claude-3.7 (high)  <left> | <right> [████░░░░] 45% (58k/128k) • 12.3k tok • $0.02
            row1_left_parts = [f"[bold {THEME_PRIMARY}]{role_formatted}[/]"]
            if is_connected and provider_display and clean_model and clean_model != "[Select model: /models]":
                model_part = f"{provider_display} › {clean_model}"
                if thinking_effort and thinking_effort != "auto":
                    model_part += f" ({thinking_effort})"
                row1_left_parts.append(f"[{THEME_SECONDARY}]{model_part}[/]")
            row1_left = STATUS_SEP.join(row1_left_parts)

            if is_connected and bool(model_name):
                ctx_val = context_used
                pct = (ctx_val / context_limit * 100) if context_limit > 0 else 0.0
                pct = min(100.0, max(0.0, pct))
                bar_len = 8
                filled = int(round((pct / 100) * bar_len))
                bar_str = "█" * filled + "░" * (bar_len - filled)
                used_formatted = format_context_tokens(ctx_val)
                cost_str = "$0" if cost_usd == 0 else f"${cost_usd:.2f}"
                tok_str = format_context_tokens(total_tokens)
                row1_right_parts = [
                    f"[{THEME_SUBTLE}][{bar_str}][/] [{THEME_SECONDARY}]{pct:.0f}% ({used_formatted}/{context_window})[/]",
                    f"[{THEME_SECONDARY}]{tok_str} tok[/]",
                    f"[{THEME_SECONDARY}]{cost_str}[/]",
                ]
                row1_right = STATUS_SEP.join(row1_right_parts)
            else:
                row1_right = f"[{THEME_SUBTLE}]Run /connect to set up API key.[/{THEME_SUBTLE}]"

            # Row 2 (Env): ~/repo/johnston • main (+12/-3) • sandbox: on • mode  <left> | <right> ⚡ 2 agents • 1 shell • 4 MCP
            max_path_len = min(50, max(25, width // 3))
            dir_text = format_display_path(directory, max_length=max_path_len)
            row2_left_parts = [f"[{THEME_SECONDARY}]{dir_text}[/]"]
            if branch and diff_text:
                row2_left_parts.append(f"[{THEME_PRIMARY}]{branch}[/] [{THEME_SECONDARY}]({diff_text})[/]")
            elif branch:
                row2_left_parts.append(f"[{THEME_PRIMARY}]{branch}[/]")
            elif diff_text:
                row2_left_parts.append(f"[{THEME_SECONDARY}]({diff_text})[/]")
            row2_left_parts.append(f"[{THEME_PRIMARY}]sandbox: on[/]" if sandbox_enabled else f"[{THEME_MUTED}]sandbox: off[/]")
            if execution_mode:
                row2_left_parts.append(f"[{THEME_SECONDARY}]{execution_mode}[/]")
            row2_left = STATUS_SEP.join(row2_left_parts)

            service_parts = []
            if subagents_active > 0:
                service_parts.append(
                    f"[{THEME_SECONDARY}]{subagents_active} agent[/]" if subagents_active == 1 else f"[{THEME_SECONDARY}]{subagents_active} agents[/]"
                )
            if active_bg_tasks > 0:
                service_parts.append(f"[{THEME_SECONDARY}]{active_bg_tasks} shell[/]")
            if mcp_total > 0:
                mcp_str = f"{mcp_active} MCP" if mcp_active == mcp_total else f"{mcp_active}/{mcp_total} MCP"
                service_parts.append(f"[{THEME_SECONDARY}]{mcp_str}[/]")

            if service_parts:
                row2_right = f"[{THEME_SECONDARY}]⚡[/] {STATUS_SEP.join(service_parts)}"
            else:
                row2_right = ""

            self._apply_two_row_grid(row1_left, row1_right, row2_left, row2_right)

    def _on_diff_updated(self) -> None:
        self.refresh_footer()

    def render_for_size(self) -> None:
        self.refresh_footer()
