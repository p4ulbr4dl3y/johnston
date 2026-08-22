import os

from rich.table import Table
from textual.widgets import Static

from core.domain.defaults.config import THEME_MUTED, THEME_PRIMARY, THEME_SECONDARY, THEME_SUBTLE
from core.infrastructure.runtime.thinking_effort import display_thinking_effort
from core.models_catalog import catalog, format_context_tokens
from widgets.git_metrics_mixin import GitMetricsMixin
from widgets.mixins.stream_frame import SPINNER_FRAMES, StreamFrameMixin


def format_display_path(raw_path: str, max_length: int = 40) -> str:
    """Format directory path for footer display with ~/ for $HOME and middle truncation if long."""
    if not raw_path:
        return ""
    try:
        norm_path = os.path.abspath(os.path.expanduser(raw_path))
        home = os.path.abspath(os.path.expanduser("~"))
        home_real = os.path.realpath(home)
        norm_real = os.path.realpath(norm_path)

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
    role_formatted: str,
    description: str = "",
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
    directory: str = "",
    branch: str = "",
    git_diff_stats,
    is_compact: bool = False,
) -> tuple[Table, list[tuple[str, str]]]:
    """Shared subagent-status table builder (2-line layout, with compact support)."""
    grid = Table.grid(expand=True)
    grid.add_column(justify="left")
    grid.add_column(justify="right")

    if is_compact:
        # Row 1 (Compact): Left [Role • Model] | Right [pct% ctx • $0.02 / tok]
        role_part = f"[bold {THEME_PRIMARY}]{role_formatted}[/]"
        if description:
            clean_desc = description.strip()
            if len(clean_desc) > 18:
                clean_desc = clean_desc[:16] + "…"
            role_part += f": [{THEME_SECONDARY}]{clean_desc}[/]"
        row1_left_parts = [role_part]
        if is_connected and clean_model and clean_model != "[Select model: /models]":
            row1_left_parts.append(f"[{THEME_SECONDARY}]{clean_model}[/]")
        row1_left = " • ".join(row1_left_parts)

        if is_connected and bool(model_name):
            pct = (context_used / context_limit * 100) if context_limit > 0 else 0.0
            pct = min(100.0, max(0.0, pct))
            pct_str = "0%" if pct == 0 else f"{pct:.0f}%"
            cost_str = "$0" if cost_usd == 0 else f"${cost_usd:.2f}"
            right_val = cost_str if cost_usd > 0 else f"{format_context_tokens(total_tokens)}t"
            row1_right = f"[{THEME_SECONDARY}]{pct_str} ctx • {right_val}[/]"
        else:
            row1_right = f"[{THEME_SUBTLE}]Run /connect[/{THEME_SUBTLE}]"

        # Row 2 (Compact): Left [dir • branch (+N/-M)] | Right [esc: back]
        dir_basename = os.path.basename(os.path.abspath(directory)) or directory
        row2_left_parts = [f"[{THEME_SECONDARY}]{dir_basename}[/]"]
        diff_text = git_diff_stats()
        if branch and diff_text:
            row2_left_parts.append(f"[{THEME_PRIMARY}]{branch}[/] [{THEME_SECONDARY}]({diff_text})[/]")
        elif branch:
            row2_left_parts.append(f"[{THEME_PRIMARY}]{branch}[/]")
        elif diff_text:
            row2_left_parts.append(f"[{THEME_SECONDARY}]({diff_text})[/]")
        row2_left = " • ".join(row2_left_parts)
        row2_right = f"[{THEME_MUTED}]esc: back[/{THEME_MUTED}]"

        grid.add_row(row1_left, row1_right)
        grid.add_row(row2_left, row2_right)
        rows = [
            (row1_left, row1_right),
            (row2_left, row2_right),
        ]
        return grid, rows

    # Full mode
    # Row 1: Left [Role: Description • Provider › Model (effort)] | Right [Context bar • tokens • cost]
    role_part = f"[bold {THEME_PRIMARY}]{role_formatted}[/bold {THEME_PRIMARY}]"
    if description:
        clean_desc = description.strip()
        if len(clean_desc) > 35:
            clean_desc = clean_desc[:32] + "…"
        role_part += f": [{THEME_SECONDARY}]{clean_desc}[/{THEME_SECONDARY}]"
    row1_left_parts = [role_part]

    if is_connected and provider_display and clean_model and clean_model != "[Select model: /models]":
        model_part = f"{provider_display} › {clean_model}"
        if thinking_effort and thinking_effort != "auto":
            model_part += f" ({thinking_effort})"
        row1_left_parts.append(f"[{THEME_SECONDARY}]{model_part}[/]")
    row1_left = "  •  ".join(row1_left_parts)

    if is_connected and model_name:
        pct = (context_used / context_limit * 100) if context_limit > 0 else 0.0
        pct = min(100.0, max(0.0, pct))
        bar_len = 8
        filled = int(round((pct / 100) * bar_len))
        bar_str = "█" * filled + "░" * (bar_len - filled)
        cost_str = "$0" if cost_usd == 0 else f"${cost_usd:.2f}"
        tok_str = format_context_tokens(total_tokens)
        row1_right_parts = [
            f"[{THEME_SUBTLE}][{bar_str}][/] [{THEME_SECONDARY}]{pct:.0f}% ({format_context_tokens(context_used)}/{context_window})[/]",
            f"[{THEME_SECONDARY}]{tok_str} tok[/]",
            f"[{THEME_SECONDARY}]{cost_str}[/]",
        ]
        row1_right = "  •  ".join(row1_right_parts)
    else:
        row1_right = f"[{THEME_SUBTLE}]Run /connect to set up API key.[/{THEME_SUBTLE}]"
    grid.add_row(row1_left, row1_right)

    # Row 2: Left [directory • branch (+N/-M)] | Right [esc: back]
    dir_text = format_display_path(directory)
    row2_left_parts = [f"[{THEME_SECONDARY}]{dir_text}[/]"]
    diff_text = git_diff_stats()
    if branch and diff_text:
        row2_left_parts.append(f"[{THEME_PRIMARY}]{branch}[/] [{THEME_SECONDARY}]({diff_text})[/]")
    elif branch:
        row2_left_parts.append(f"[{THEME_PRIMARY}]{branch}[/]")
    elif diff_text:
        row2_left_parts.append(f"[{THEME_SECONDARY}]({diff_text})[/]")
    row2_left = "  •  ".join(row2_left_parts)

    row2_right = f"[{THEME_MUTED}]esc: back[/{THEME_MUTED}]"
    grid.add_row(row2_left, row2_right)

    rows = [
        (row1_left, row1_right),
        (row2_left, row2_right),
    ]
    return grid, rows


class StatusFooter(GitMetricsMixin, StreamFrameMixin, Static):
    """Two-line status footer below chat"""

    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, *args, is_subagent: bool = False, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.is_subagent: bool = is_subagent
        self.is_generating: bool = False
        self._spinner_idx: int = 0
        self._spinner_timer = None
        self._mcp_poll_timer = None
        self._resize_timer = None
        self._last_resize_size = None

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
        if self.is_subagent:
            if getattr(self, "_subagent_session", None):
                if getattr(self, "_last_grid_rows", None):
                    self._render_stream_frame()
                else:
                    self.update_subagent_footer(self._subagent_session)
        elif hasattr(self, "_last_status_args"):
            # Only the spinner frame changed: redraw cheaply from cached rows
            # instead of rebuilding git/table data on every tick.
            self._render_stream_frame()
        else:
            self.refresh_footer()

    def on_mount(self) -> None:
        if not self.is_subagent:
            self.refresh_footer()
            # While MCP servers are still warming up (or their tool counts change),
            # poll so the footer spinner and loaded-server count stay current even
            # when not generating.
            self._mcp_poll_timer = self.set_interval(1.0, self._poll_mcp_refresh)

    def on_unmount(self) -> None:
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
        if getattr(self, "_resize_timer", None):
            try:
                self._resize_timer.stop()
            except Exception:
                pass
            self._resize_timer = None

    def _poll_mcp_refresh(self) -> None:
        try:
            from core.infrastructure.mcp import get_mcp_manager

            mm = get_mcp_manager()
            is_loading = mm.is_loading()
            was_loading = getattr(self, "_mcp_was_loading", False)
            if is_loading or was_loading:
                self._mcp_was_loading = is_loading
                self.refresh_footer()
                return
            # Not loading: keep the loaded-server count live so the footer
            # reflects MCP servers that finished warming up after the window
            # above (or drifted since). `refresh_footer` caches mcp servers for
            # 5s, but the client/tool state is read fresh each call, so this is
            # cheap enough at a 1s cadence.
            active = self._active_mcp_count(get_mcp_manager().load_servers())
            if active != getattr(self, "_mcp_last_active", None):
                self._mcp_last_active = active
                self.refresh_footer()
        except Exception:
            pass

    def _active_mcp_count(self, servers) -> int:
        """Count enabled MCP servers that finished loading tools (no error, has tools)."""
        from core.infrastructure.mcp import get_mcp_manager

        count_fn = getattr(get_mcp_manager(), "active_server_count", None)
        if callable(count_fn):
            try:
                return count_fn(servers) or 0
            except Exception:
                pass
        return 0

    def refresh_footer(self) -> None:
        try:
            from widgets.app.status_state import build_status_kwargs

            kwargs = build_status_kwargs(self.app, widget=self)
            self._last_status_args = kwargs
            self.update_status(**kwargs)
        except Exception:
            self.update_status(provider_key="default")

    def update_subagent_footer(self, session) -> None:
        """Render footer for a subagent session using its own agent/dir/branch/metrics."""
        self._subagent_session = session
        try:
            from widgets.app.status_state import build_subagent_status_kwargs

            # Live spinner while the subagent session is still streaming/running.
            # (widget manages spinner timer state; aggregation stays in status_state)
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

            kwargs = build_subagent_status_kwargs(
                self.app,
                session,
                spinner_running=self.is_generating,
                spinner_idx=self._spinner_idx,
            )
            self._render_subagent(*kwargs, branch_name=getattr(session, "branch_name", ""))
        except Exception:
            pass

    def _render_subagent(
        self,
        role_formatted: str,
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
        directory: str = "",
        branch_name: str = "",
    ) -> None:
        """Footer for the subagent screen: role/model, context/tokens, dir/branch."""
        branch = branch_name or self._git_branch(cwd=directory)
        grid, rows = _build_subagent_grid(
            role_formatted=role_formatted,
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
        )
        self._last_grid_rows = rows
        self.update(grid)

    def _mcp_footer_text(self, mcp_active: int, mcp_total: int, prefix: str = "MCP:") -> str:
        """MCP indicator: show active/total count as 'N/M', or '0' when none configured."""
        if mcp_total <= 0:
            return f"{prefix} [{THEME_SECONDARY}]0[/{THEME_SECONDARY}]"
        return f"{prefix} [{THEME_SECONDARY}]{mcp_active}/{mcp_total}[/{THEME_SECONDARY}]"

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
    ) -> None:
        if not directory:
            directory = os.getcwd()

        dir_text = format_display_path(directory)
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

        if self.is_subagent:
            self._render_subagent(
                role_formatted=role_formatted,
                provider_display=provider_display or provider_key.capitalize(),
                clean_model=clean_model or "[Select model: /models]",
                is_connected=is_connected,
                model_name=model_name,
                context_used=context_used,
                total_tokens=total_tokens,
                context_limit=context_limit,
                context_window=context_window,
                cost_usd=cost_usd,
                thinking_effort=thinking_effort,
                directory=directory,
            )
            return

        app_width = 80
        try:
            if self.app and self.app.size:
                app_width = self.app.size.width
        except Exception:
            pass

        width = (
            self.size.width
            if (self.size and self.size.width > 0)
            else app_width
        )
        is_compact = width > 0 and width < 75

        if is_compact:
            branch = self._git_branch(cwd=directory)
            diff_text = self._git_diff_stats(cwd=directory)

            # Row 1 (LLM): ⠋ Action • claude-3.7  <left> | <right> 45% ctx • $0.02
            row1_left_parts = [f"[bold {THEME_PRIMARY}]{role_formatted}[/]"]
            if is_connected and clean_model and clean_model != "[Select model: /models]":
                row1_left_parts.append(f"[{THEME_SECONDARY}]{clean_model}[/]")
            row1_left = " • ".join(row1_left_parts)

            if is_connected and bool(model_name):
                pct = (context_used / context_limit * 100) if context_limit > 0 else 0.0
                pct = min(100.0, max(0.0, pct))
                pct_str = "0%" if pct == 0 else f"{pct:.0f}%"
                cost_str = "$0" if cost_usd == 0 else f"${cost_usd:.2f}"
                right_val = cost_str if cost_usd > 0 else f"{format_context_tokens(total_tokens)}t"
                row1_right = f"[{THEME_SECONDARY}]{pct_str} ctx • {right_val}[/]"
            else:
                row1_right = f"[{THEME_SUBTLE}]Run /connect[/{THEME_SUBTLE}]"

            # Row 2 (Env): johnston • main (+3/-1)  <left> | <right> ⚡ 2a • 1s
            dir_basename = os.path.basename(os.path.abspath(directory)) or directory
            row2_left_parts = [f"[{THEME_SECONDARY}]{dir_basename}[/]"]
            if branch and diff_text:
                row2_left_parts.append(f"[{THEME_PRIMARY}]{branch}[/] [{THEME_SECONDARY}]({diff_text})[/]")
            elif branch:
                row2_left_parts.append(f"[{THEME_PRIMARY}]{branch}[/]")
            elif diff_text:
                row2_left_parts.append(f"[{THEME_SECONDARY}]({diff_text})[/]")
            row2_left = " • ".join(row2_left_parts)

            task_parts = []
            if subagents_active > 0:
                task_parts.append(f"{subagents_active}a")
            if active_bg_tasks > 0:
                task_parts.append(f"{active_bg_tasks}s")
            if mcp_total > 0:
                task_parts.append(f"{mcp_active}mcp")
            row2_right = f"[{THEME_SECONDARY}]⚡ {' • '.join(task_parts)}[/]" if task_parts else ""

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
            return
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
            row1_left = "  •  ".join(row1_left_parts)

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
                row1_right = "  •  ".join(row1_right_parts)
            else:
                row1_right = f"[{THEME_SUBTLE}]Run /connect to set up API key.[/{THEME_SUBTLE}]"

            # Row 2 (Env): ~/repo/johnston • main (+12/-3)  <left> | <right> ⚡ 2 agents • 1 shell • 4 MCP
            max_path_len = min(50, max(25, width // 3))
            dir_text = format_display_path(directory, max_length=max_path_len)
            row2_left_parts = [f"[{THEME_SECONDARY}]{dir_text}[/]"]
            if branch and diff_text:
                row2_left_parts.append(f"[{THEME_PRIMARY}]{branch}[/] [{THEME_SECONDARY}]({diff_text})[/]")
            elif branch:
                row2_left_parts.append(f"[{THEME_PRIMARY}]{branch}[/]")
            elif diff_text:
                row2_left_parts.append(f"[{THEME_SECONDARY}]({diff_text})[/]")
            row2_left = "  •  ".join(row2_left_parts)

            service_parts = []
            if subagents_active > 0:
                service_parts.append(
                    f"{subagents_active} agent" if subagents_active == 1 else f"{subagents_active} agents"
                )
            if active_bg_tasks > 0:
                service_parts.append(f"{active_bg_tasks} shell")
            if mcp_total > 0:
                service_parts.append(f"{mcp_active} MCP" if mcp_active == mcp_total else f"{mcp_active}/{mcp_total} MCP")

            if service_parts:
                row2_right = f"[{THEME_SECONDARY}]⚡ {'  •  '.join(service_parts)}[/]"
            else:
                row2_right = ""

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
            return

    def _on_diff_updated(self) -> None:
        self.refresh_footer()

    def on_resize(self, event) -> None:
        size = getattr(event, "size", None)
        if size is not None and size == self._last_resize_size:
            return
        self._last_resize_size = size
        if self._resize_timer is not None:
            self._resize_timer.stop()
            self._resize_timer = None
        self._resize_timer = self.set_timer(0.15, self._debounced_refresh)

    def _debounced_refresh(self) -> None:
        self._resize_timer = None
        self.refresh_footer()


class SubagentStatusFooter(GitMetricsMixin, StreamFrameMixin, Static):
    """Dedicated status footer for subagent screen, isolated from main app footer."""

    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__("", *args, **kwargs)
        self.session = None
        self.is_generating: bool = False
        self._spinner_idx: int = 0
        self._spinner_timer = None
        self._diff_text: str = ""
        self._diff_time: float = 0.0
        self._diff_loading: bool = False
        self._last_grid_rows: list[tuple[str, str]] | None = None

    def on_mount(self) -> None:
        self._render_footer()

    def on_unmount(self) -> None:
        if self._spinner_timer:
            try:
                self._spinner_timer.stop()
            except Exception:
                pass
            self._spinner_timer = None

    def update_session(self, session) -> None:
        """Update with a subagent session record (AgentSession) and refresh render."""
        self.session = session
        if not session:
            self._render_footer()
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

        self._render_footer()

    def _spin(self) -> None:
        self._spinner_idx = (self._spinner_idx + 1) % len(SPINNER_FRAMES)
        if getattr(self, "_last_grid_rows", None):
            self._render_stream_frame()
        else:
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
            role = getattr(agent, "role", "worker") if agent else getattr(session, "role", "worker")
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
            providers = pm.load_providers() if pm else {}
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

            history_tokens = estimate_tokens(session.messages) if getattr(session, "messages", None) else 0
            context_used = metrics.get("context_used") or getattr(session, "last_context_tokens", 0) or history_tokens
            total_tokens = metrics.get("total_tokens") or getattr(session, "total_tokens", 0) or history_tokens
            cost_usd = metrics.get("cost_usd") or getattr(session, "cost_usd", 0.0)
            if cost_usd == 0.0 and total_tokens > 0 and (provider_key or model_name):
                pricing = catalog.get_model_pricing(provider_key, model_name)
                if pricing:
                    p_in = pricing.get("prompt", 0.0)
                    p_out = pricing.get("completion", 0.0)
                    half = total_tokens / 2.0
                    cost_usd = half * p_in + half * p_out

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

            app_width = 80
            try:
                if cur_app and getattr(cur_app, "size", None):
                    raw_w = getattr(cur_app.size, "width", 80)
                    if isinstance(raw_w, int):
                        app_width = raw_w
            except Exception:
                pass

            raw_size_w = getattr(getattr(self, "size", None), "width", 0)
            size_w = raw_size_w if isinstance(raw_size_w, int) else 0
            width = size_w if size_w > 0 else app_width
            is_compact = isinstance(width, int) and width > 0 and width < 75

            role_formatted = f"{SPINNER_FRAMES[self._spinner_idx % len(SPINNER_FRAMES)]} " if self.is_generating else ""
            role_formatted += role.capitalize()

            branch = getattr(session, "branch_name", "") or self._git_branch(cwd=directory)
            description = getattr(session, "description", "")
            grid, rows = _build_subagent_grid(
                role_formatted=role_formatted,
                description=description,
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
            )

            self._last_grid_rows = rows
            self.update(grid)
        except Exception:
            pass

    def _on_diff_updated(self) -> None:
        self._render_footer()

    def on_resize(self, event) -> None:
        size = getattr(event, "size", None)
        if size is not None and size == getattr(self, "_last_resize_size", None):
            return
        self._last_resize_size = size
        timer = getattr(self, "_resize_timer", None)
        if timer is not None:
            timer.stop()
            self._resize_timer = None
        self._resize_timer = self.set_timer(0.15, self._debounced_render)

    def _debounced_render(self) -> None:
        self._resize_timer = None
        self._render_footer()
