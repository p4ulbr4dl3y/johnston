"""Subagent screen header and footer widgets."""
from __future__ import annotations

import os

from rich.table import Table
from textual.widgets import Static

from core.infrastructure.runtime.thinking_effort import display_thinking_effort
from core.models_catalog import catalog, format_context_tokens
from widgets.git_metrics_mixin import GitMetricsMixin
from widgets.mixins.resize_debounce import ResizeDebounceMixin
from widgets.mixins.stream_frame import SPINNER_FRAMES, StreamFrameMixin
from widgets.presentation.widgets.footer_layout import (
    _build_subagent_grid,
    get_theme_colors,
)
from widgets.utils.responsive import BREAKPOINT_COMPACT, is_compact_width, resolve_width
from widgets.utils.row_format import ellipsize


class SubagentStatusFooter(ResizeDebounceMixin, GitMetricsMixin, Static):
    """Dedicated status footer for subagent screen, isolated from main app footer."""

    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__("", *args, **kwargs)
        self.session = None
        self._diff_text: str = ""
        self._diff_time: float = 0.0
        self._diff_loading: bool = False
        self._last_grid_rows: list[tuple[str, str]] | None = None

    def on_mount(self) -> None:
        self._render_footer()

    def on_unmount(self) -> None:
        self.cancel_resize_timer()

    def update_session(self, session) -> None:
        """Update with a subagent session record (AgentSession) and refresh render."""
        self.session = session
        self._render_footer()

    def _render_footer(self) -> None:
        grid = Table.grid(expand=True)
        grid.add_column(justify="left")
        grid.add_column(justify="right")
        if not self.session:
            grid.add_row("", "")
            grid.add_row("", "")
            self._last_grid_rows = [("", ""), ("", "")]
            self.update(grid)
            return
        session = self.session
        try:
            cur_app = getattr(self, "_harness_app", None)
            if cur_app is None:
                try:
                    cur_app = self.app
                except Exception:
                    cur_app = None

            agent = getattr(session, "agent", None)
            app_agent = getattr(cur_app, "agent", None) if cur_app else None
            effort_val = getattr(agent, "thinking_effort", None) if agent else getattr(app_agent, "thinking_effort", None)
            thinking_effort = display_thinking_effort(effort_val) if effort_val else "auto"
            metrics = agent.get_metrics() if (agent and hasattr(agent, "get_metrics")) else {}
            provider_key = (
                getattr(agent, "provider_key", "")
                if agent
                else (getattr(app_agent, "provider_key", "") if app_agent else "")
            )

            pm = getattr(cur_app, "pm", None) if cur_app else None
            if not provider_key and pm:
                provider_key = pm.get_active_provider_key()
            providers = getattr(pm, "providers", None) or (pm.load_providers() if pm else {})
            provider_info = providers.get(provider_key, {}) if isinstance(providers, dict) else {}
            provider_display = provider_info.get("name", provider_key) if provider_info else provider_key
            is_connected = pm.is_provider_connected(provider_key, provider_info) if (pm and provider_key) else False

            model_name = (
                getattr(agent, "model", "")
                if agent
                else (getattr(app_agent, "model", "") if app_agent else provider_info.get("model", ""))
            )
            clean_model = catalog.get_model_display_name(provider_key, model_name) if model_name else ""
            if not clean_model:
                clean_model = "[Select model: /models]"

            directory = getattr(session, "project_dir", "") or os.getcwd()

            from core.infrastructure.runtime.token_util import estimate_tokens

            msgs = getattr(session, "messages", None)
            msg_count = len(msgs) if msgs else 0
            cached_count = getattr(self, "_cached_msg_count", None)
            cached_sess_id = getattr(self, "_cached_sess_id", None)
            cur_sess_id = getattr(session, "id", None)
            if cached_count == msg_count and cached_sess_id == cur_sess_id and hasattr(self, "_cached_history_tokens"):
                history_tokens = self._cached_history_tokens
            else:
                history_tokens = estimate_tokens(msgs) if msgs else 0
                self._cached_msg_count = msg_count
                self._cached_sess_id = cur_sess_id
                self._cached_history_tokens = history_tokens

            context_used = metrics.get("context_used") or getattr(session, "last_context_tokens", 0) or history_tokens
            total_tokens = metrics.get("total_tokens") or getattr(session, "total_tokens", 0) or history_tokens
            cost_usd = metrics.get("cost_usd") or getattr(session, "cost_usd", 0.0)
            if cost_usd == 0.0 and total_tokens > 0 and (provider_key or model_name):
                cost_usd = catalog.estimate_cost_from_totals(provider_key, model_name, total_tokens)

            raw_limit = (
                metrics.get("context_limit")
                or getattr(agent, "context_limit", None)
                or (getattr(app_agent, "context_limit", 128000) if app_agent else 128000)
            )
            try:
                context_limit = int(raw_limit) if raw_limit is not None else 128000
            except (ValueError, TypeError):
                context_limit = 128000
            context_window = metrics.get("context") or format_context_tokens(context_limit)

            width = resolve_width(self)
            is_compact = is_compact_width(width)

            sandbox_val = getattr(session, "sandbox_enabled", None)
            if sandbox_val is None and agent:
                sandbox_val = getattr(agent, "sandbox_enabled", None)
            if sandbox_val is None and cur_app:
                sandbox_val = getattr(cur_app, "sandbox_enabled", None)
            if sandbox_val is None:
                if getattr(session, "role", "") == "explorer" or getattr(agent, "read_only", False):
                    sandbox_val = True
                else:
                    from core.infrastructure.config.config_helpers import load_sandbox_config

                    sandbox_val = load_sandbox_config()
            sandbox_enabled = bool(sandbox_val)

            from core.permission_manager import PermissionManager

            pm_inst = PermissionManager.get_instance()
            execution_mode = pm_inst.execution_mode.value if pm_inst else "review"

            branch = getattr(session, "branch_name", "") or self._git_branch(cwd=directory)
            grid, rows = _build_subagent_grid(
                provider_display=provider_display,
                clean_model=clean_model,
                is_connected=is_connected,
                model_name=model_name,
                context_used=context_used,
                total_tokens=total_tokens,
                context_limit=context_limit,
                context_window=context_window,
                cost_usd=cost_usd,
                thinking_effort=thinking_effort,
                directory=directory,
                branch=branch,
                git_diff_stats=lambda: self._git_diff_stats(cwd=directory),
                is_compact=is_compact,
                sandbox_enabled=sandbox_enabled,
                execution_mode=execution_mode,
            )

            self._last_grid_rows = rows
            self.update(grid)
        except Exception:
            pass

    def _on_diff_updated(self) -> None:
        self._render_footer()

    def render_for_size(self) -> None:
        self._render_footer()


class SubagentHeader(ResizeDebounceMixin, StreamFrameMixin, Static):
    """Single-line top header for subagent screen displaying role, description and esc hint."""

    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, *args, from_tasks: bool = False, **kwargs) -> None:
        super().__init__("", *args, **kwargs)
        self.session = None
        self.from_tasks = from_tasks
        self.is_generating: bool = False
        self._spinner_idx: int = 0
        self._spinner_timer = None
        self._last_grid_rows: list[tuple[str, str]] | None = None

    def on_mount(self) -> None:
        self._render_header()

    def on_unmount(self) -> None:
        if self._spinner_timer:
            try:
                self._spinner_timer.stop()
            except Exception:
                pass
            self._spinner_timer = None
        self.cancel_resize_timer()

    def update_session(self, session) -> None:
        """Update with a subagent session record and refresh header render."""
        self.session = session
        if not session:
            self._render_header()
            return

        is_running = getattr(session, "status", "") == "running"
        if is_running and not self.is_generating:
            self.is_generating = True
            if not self._spinner_timer:
                self._spinner_timer = self.set_interval(0.2, self._spin)
        elif not is_running and self.is_generating:
            self.is_generating = False
            if self._spinner_timer:
                self._spinner_timer.stop()
                self._spinner_timer = None
            self._spinner_idx = 0

        self._render_header()

    def _spin(self) -> None:
        self._spinner_idx = (self._spinner_idx + 1) % len(SPINNER_FRAMES)
        if getattr(self, "_last_grid_rows", None):
            self._render_stream_frame()
        else:
            self._render_header()

    def render_for_size(self) -> None:
        self._render_header()

    def _render_header(self) -> None:
        grid = Table.grid(expand=True)
        grid.add_column(justify="left")
        grid.add_column(justify="right")

        t_primary, t_secondary, t_muted, _ = get_theme_colors()

        if not self.session:
            esc_label = "esc: back" if getattr(self, "from_tasks", False) else "esc: close"
            grid.add_row("", f"[{t_muted}]{esc_label}[/{t_muted}]")
            self._last_grid_rows = [("", f"[{t_muted}]{esc_label}[/{t_muted}]")]
            self.update(grid)
            return

        try:
            session = self.session
            cur_app = getattr(self, "_harness_app", None)
            if cur_app is None:
                try:
                    cur_app = self.app
                except Exception:
                    cur_app = None

            agent = getattr(session, "agent", None)
            role = getattr(agent, "role", "worker") if agent else getattr(session, "role", "worker")
            role_str = role.capitalize()
            if self.is_generating:
                frame = SPINNER_FRAMES[self._spinner_idx % len(SPINNER_FRAMES)]
                role_formatted = f"{frame} {role_str}"
            else:
                role_formatted = role_str

            width = resolve_width(self)
            is_compact = is_compact_width(width, breakpoint=BREAKPOINT_COMPACT)

            role_part = f"[bold {t_primary}]{role_formatted}[/]"
            description = (getattr(session, "description", "") or "").strip()
            if description:
                max_desc = max(8, width - len(role_str) - (12 if is_compact else 22))
                clean_desc = ellipsize(description, max_desc)
                role_part += f": [{t_secondary}]{clean_desc}[/]"

            row_left = role_part
            esc_label = (
                "esc: back"
                if getattr(self, "from_tasks", False)
                else ("esc" if is_compact else "esc: close")
            )
            row_right = f"[{t_muted}]{esc_label}[/{t_muted}]"

            grid.add_row(row_left, row_right)
            self._last_grid_rows = [(row_left, row_right)]
            self.update(grid)
        except Exception:
            pass
