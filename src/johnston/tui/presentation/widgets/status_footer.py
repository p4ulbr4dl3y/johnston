"""Two-line status footer below chat."""
from __future__ import annotations

from rich.table import Table
from textual.widgets import Static

from johnston.tui.adapters import core_bridge
from johnston.tui.mixins.git_metrics import GitMetricsMixin
from johnston.tui.mixins.resize_debounce import ResizeDebounceMixin
from johnston.tui.mixins.stream_frame import SPINNER_FRAMES, StreamFrameMixin
from johnston.tui.presentation.widgets.footer_layout import (
    format_display_path,  # noqa: F401  (re-exported; tests import it from this module)
)
from johnston.tui.presentation.widgets.footer_render import (
    render_compact_rows,
    render_wide_rows,
    resolve_status_defaults,
)
from johnston.tui.utils.responsive import is_compact_width, resolve_width

__all__ = [
    "StatusFooter",
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
            if not self._spinner_timer and self.is_mounted:
                try:
                    # Spinner is cosmetic; 0.3s tick halves UI-loop wakeups vs 0.15s.
                    self._spinner_timer = self.set_interval(0.3, self._spin)
                except Exception:
                    self._spinner_timer = None
        else:
            if self._spinner_timer:
                try:
                    self._spinner_timer.stop()
                except Exception:
                    pass
                self._spinner_timer = None
            self._spinner_idx = 0
        self.refresh_footer()

    def _spin(self) -> None:
        self._spinner_idx = (self._spinner_idx + 1) % len(SPINNER_FRAMES)
        if getattr(self, "_last_grid_rows", None):
            self._render_stream_frame()
        else:
            self.refresh_footer()

    def on_mount(self) -> None:
        if self.is_generating and not self._spinner_timer:
            try:
                self._spinner_timer = self.set_interval(0.3, self._spin)
            except Exception:
                self._spinner_timer = None
        self.refresh_footer()
        try:

            mgr = core_bridge.get_mcp_manager()
            if mgr and hasattr(mgr, "add_listener"):
                mgr.add_listener(self._on_mcp_event)
        except Exception:
            pass

    def on_unmount(self) -> None:
        try:

            mgr = core_bridge.get_mcp_manager()
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
            from johnston.tui.app.status_state import refresh_footer_cache

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
            from johnston.tui.app.status_state import build_status_kwargs

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
        if clean_model is None and model_name:
            client = getattr(self.app, "client", None) if self.app else None
            if client and hasattr(client, "get_model_info"):
                try:
                    info = client.get_model_info(provider_key, model_name)
                    clean_model = getattr(info, "display_name", "")
                except Exception:
                    clean_model = ""

        resolved = resolve_status_defaults(
            provider_key=provider_key,
            provider_display=provider_display,
            is_connected=is_connected,
            model_name=model_name,
            clean_model=clean_model,
            agent_role=agent_role,
            directory=directory,
            app=self.app,
            is_generating=self.is_generating,
            spinner_idx=self._spinner_idx,
        )
        directory = resolved["directory"]
        is_connected = resolved["is_connected"]
        role_formatted = resolved["role_formatted"]

        width = resolve_width(self)
        is_compact = is_compact_width(width)

        if is_compact:
            branch = self._git_branch(cwd=directory)
            diff_text = self._git_diff_stats(cwd=directory)
            row1_left, row1_right, row2_left, row2_right = render_compact_rows(
                width=width,
                role_formatted=role_formatted,
                provider_display=resolved["provider_display"],
                is_connected=is_connected,
                clean_model=resolved["clean_model"],
                model_name=model_name,
                context_used=context_used,
                context_limit=context_limit,
                cost_usd=cost_usd,
                total_tokens=total_tokens,
                directory=directory,
                branch=branch,
                diff_text=diff_text,
                sandbox_enabled=sandbox_enabled,
                execution_mode=execution_mode,
                subagents_active=subagents_active,
                active_bg_tasks=active_bg_tasks,
                mcp_active=mcp_active,
                mcp_total=mcp_total,
                is_generating=self.is_generating,
            )
        else:
            branch = self._git_branch(cwd=directory)
            diff_text = self._git_diff_stats(cwd=directory)
            row1_left, row1_right, row2_left, row2_right = render_wide_rows(
                width=width,
                role_formatted=role_formatted,
                provider_display=resolved["provider_display"],
                is_connected=is_connected,
                clean_model=resolved["clean_model"],
                model_name=model_name,
                thinking_effort=thinking_effort,
                context_used=context_used,
                context_limit=context_limit,
                context_window=context_window,
                total_tokens=total_tokens,
                cost_usd=cost_usd,
                directory=directory,
                branch=branch,
                diff_text=diff_text,
                sandbox_enabled=sandbox_enabled,
                execution_mode=execution_mode,
                subagents_active=subagents_active,
                active_bg_tasks=active_bg_tasks,
                mcp_active=mcp_active,
                mcp_total=mcp_total,
                is_generating=self.is_generating,
            )

        self._apply_two_row_grid(row1_left, row1_right, row2_left, row2_right)

    def _on_diff_updated(self) -> None:
        self.refresh_footer()

    def render_for_size(self) -> None:
        self.refresh_footer()
