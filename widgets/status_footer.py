import os

from rich.table import Table
from textual.widgets import Static

from core.domain.defaults.config import THEME_PRIMARY, THEME_SECONDARY, THEME_SUBTLE
from core.infrastructure.runtime.thinking_effort import display_thinking_effort
from core.models_catalog import catalog, format_context_tokens
from widgets.git_metrics_mixin import GitMetricsMixin

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


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
) -> tuple[Table, list[tuple[str, str]]]:
    """Shared subagent-status table builder.

    Used by both ``StatusFooter._render_subagent`` and
    ``SubagentStatusFooter._render_footer`` to deduplicate ~60 lines of
    identical table-construction logic.
    """
    grid = Table.grid(expand=True)
    grid.add_column(justify="left")
    grid.add_column(justify="right")

    row1_left_parts = [f"[bold {THEME_PRIMARY}]{role_formatted}[/bold {THEME_PRIMARY}]"]
    if is_connected and provider_display and clean_model and clean_model != "[Select model: /models]":
        row1_left_parts.append(f"[{THEME_SECONDARY}]{provider_display} › {clean_model}[/]")
    row1_left = "  •  ".join(row1_left_parts)
    row1_right = ""
    grid.add_row(row1_left, row1_right)

    # Line 2: [context]  [tokens • cost • effort]
    if is_connected and model_name:
        pct = (context_used / context_limit * 100) if context_limit > 0 else 0.0
        pct = min(100.0, max(0.0, pct))
        bar_len = 8
        filled = int(round((pct / 100) * bar_len))
        bar_str = "█" * filled + "░" * (bar_len - filled)
        row2_left = (
            f"Context: [{THEME_SUBTLE}][{bar_str}][/] "
            f"[{THEME_SECONDARY}]{pct:.1f}% ({format_context_tokens(context_used)}/{context_window})[/]"
        )
    else:
        row2_left = f"[{THEME_SUBTLE}]Run /connect to set up API key.[/{THEME_SUBTLE}]"
    cost_str = "$0" if cost_usd == 0 else f"${cost_usd:.4f}"
    row2_right_parts = [
        f"[{THEME_SECONDARY}]{total_tokens:,} tok[/]",
        f"[{THEME_SECONDARY}]{cost_str}[/]",
        f"[{THEME_SECONDARY}]effort:{thinking_effort}[/]",
    ]
    row2_right = "  •  ".join(row2_right_parts)
    grid.add_row(row2_left, row2_right)

    # Line 3: [directory • branch • +N/-M]
    dir_text = format_display_path(directory)
    row3_left_parts = [f"[{THEME_SECONDARY}]{dir_text}[/]"]
    if branch:
        row3_left_parts.append(f"[{THEME_PRIMARY}]{branch}[/]")
    diff_text = git_diff_stats()
    if diff_text:
        row3_left_parts.append(f"[{THEME_SECONDARY}]{diff_text}[/]")
    row3_left = "  •  ".join(row3_left_parts)
    row3_right = ""
    grid.add_row(row3_left, row3_right)

    rows = [
        (row1_left, row1_right),
        (row2_left, row2_right),
        (row3_left, row3_right),
    ]
    return grid, rows


class StatusFooter(GitMetricsMixin, Static):
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

    def _render_stream_frame(self) -> None:
        """Redraw only the animated frame from cached status rows (no git/rebuild)."""
        if not self.is_generating:
            return
        rows = getattr(self, "_last_grid_rows", None)
        if rows is None:
            return
        try:
            frame = SPINNER_FRAMES[self._spinner_idx % len(SPINNER_FRAMES)]
            grid = Table.grid(expand=True)
            if rows and len(rows[0]) == 1:
                grid.add_column(justify="left")
                for i, row in enumerate(rows):
                    cell = row[0]
                    if i == 0:
                        cell = self._swap_frame(cell, frame)
                    grid.add_row(cell)
            else:
                grid.add_column(justify="left")
                grid.add_column(justify="right")
                for i, (left, right) in enumerate(rows):
                    if i == 0:
                        left = self._swap_frame(left, frame)
                    grid.add_row(left, right)
            self.update(grid)
        except Exception:
            pass

    @staticmethod
    def _swap_frame(left: str, frame: str) -> str:
        """Replace the old spinner char in the cached left cell with the new frame."""
        try:
            idx = left.index("]") + 1
            return left[:idx] + frame + left[idx + 1 :]
        except Exception:
            return left

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

        mm = get_mcp_manager()
        count = 0
        for s in servers:
            s_name = s.get("name")
            cmd = s.get("command")
            url = s.get("url")
            if url and not cmd:
                continue
            if s.get("disabled", False):
                continue
            client = mm.clients.get(s_name) if hasattr(mm, "clients") else None
            if client is None:
                continue
            if getattr(client, "last_error", None):
                continue
            if not getattr(client, "tools", None):
                continue
            count += 1
        return count

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
        """MCP indicator: show active/total count as 'N/M'."""
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
    ) -> None:
        if not directory:
            directory = os.getcwd()

        dir_text = format_display_path(directory)
        if provider_display is None:
            provider_display = provider_key.capitalize() if provider_key else ""
        if is_connected is None:
            pm = getattr(self.app, "pm", None)
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

        width = (
            self.size.width
            if (self.size and self.size.width > 0)
            else (self.app.size.width if (self.app and self.app.size) else 80)
        )
        is_compact = width > 0 and width < 75

        if is_compact:
            branch = self._git_branch(cwd=directory)

            row1_parts = [f"[bold {THEME_PRIMARY}]{role_formatted}[/]"]
            if is_connected and provider_display and clean_model and clean_model != "[Select model: /models]":
                row1_parts.append(f"[{THEME_SECONDARY}]{clean_model}[/]")
            row1_parts.append(self._mcp_footer_text(mcp_active, mcp_total))
            row1 = " • ".join(row1_parts)

            row2_parts = [f"[{THEME_SECONDARY}]{dir_text}[/]"]
            if branch:
                row2_parts.append(f"[{THEME_PRIMARY}]{branch}[/]")
            diff_text = self._git_diff_stats(cwd=directory)
            if diff_text:
                row2_parts.append(f"[{THEME_SECONDARY}]{diff_text}[/]")
            row2_parts.append(f"[{THEME_SECONDARY}]{total_tokens:,}t[/]")
            row2 = " • ".join(row2_parts)

            if is_connected and bool(model_name):
                pct = (context_used / context_limit * 100) if context_limit > 0 else 0.0
                pct = min(100.0, max(0.0, pct))
                pct_str = "0%" if pct == 0 else f"{pct:.0f}%"
                row3 = f"Ctx: [{THEME_SECONDARY}]{pct_str}[/]"
                task_parts = []
                if subagents_active > 0:
                    task_parts.append(f"{subagents_active}agent")
                if active_bg_tasks > 0:
                    task_parts.append(f"{active_bg_tasks}shell")
                if task_parts:
                    row3 += f" • [{THEME_SECONDARY}]{', '.join(task_parts)}[/]"
            else:
                row3 = f"[{THEME_SUBTLE}]Run /connect[/{THEME_SUBTLE}]"

            grid = Table.grid(expand=True)
            grid.add_column(justify="left")
            grid.add_row(row1)
            grid.add_row(row2)
            if row3:
                grid.add_row(row3)
            grid.add_row("", "")
            cells = [(row1,), (row2,)]
            if row3:
                cells.append((row3,))
            cells.append(("",))
            self._last_grid_rows = cells
            self.update(grid)
            return
        else:
            branch = self._git_branch(cwd=directory)

            # Line 1: [role • provider › model]  [skills • mcp]
            row1_left_parts = [f"[bold {THEME_PRIMARY}]{role_formatted}[/]"]
            if is_connected and provider_display and clean_model and clean_model != "[Select model: /models]":
                row1_left_parts.append(f"[{THEME_SECONDARY}]{provider_display} › {clean_model}[/]")
            row1_left = "  •  ".join(row1_left_parts)
            row1_right_parts = [
                f"Skills: [{THEME_SECONDARY}]{skills_visible}/{skills_total}[/]"
                if skills_total > 0
                else f"Skills: [{THEME_SECONDARY}]0[/]",
                self._mcp_footer_text(mcp_active, mcp_total, prefix="MCP:"),
            ]
            row1_right = "  •  ".join(row1_right_parts)

            # Line 2: [context]  [tokens • cost • effort]
            if is_connected and bool(model_name):
                ctx_val = context_used
                pct = (ctx_val / context_limit * 100) if context_limit > 0 else 0.0
                pct = min(100.0, max(0.0, pct))
                bar_len = 8
                filled = int(round((pct / 100) * bar_len))
                bar_str = "█" * filled + "░" * (bar_len - filled)
                used_formatted = format_context_tokens(ctx_val)
                row2_left = (
                    f"Context: [{THEME_SUBTLE}][{bar_str}][/] "
                    f"[{THEME_SECONDARY}]{pct:.1f}% ({used_formatted}/{context_window})[/]"
                )
            else:
                row2_left = f"[{THEME_SUBTLE}]Run /connect to set up API key.[/{THEME_SUBTLE}]"
            cost_str = "$0" if cost_usd == 0 else f"${cost_usd:.4f}"
            row2_right_parts = [
                f"[{THEME_SECONDARY}]{total_tokens:,} tok[/]",
                f"[{THEME_SECONDARY}]{cost_str}[/]",
                f"[{THEME_SECONDARY}]effort:{thinking_effort}[/]",
            ]
            row2_right = "  •  ".join(row2_right_parts)

            # Line 3: [directory • branch • +N/-M]  [agents • shells]
            dir_text = format_display_path(directory)
            row3_left_parts = [f"[{THEME_SECONDARY}]{dir_text}[/]"]
            if branch:
                row3_left_parts.append(f"[{THEME_PRIMARY}]{branch}[/]")
            diff_text = self._git_diff_stats(cwd=directory)
            if diff_text:
                row3_left_parts.append(f"[{THEME_SECONDARY}]{diff_text}[/]")
            row3_left = "  •  ".join(row3_left_parts)

            row3_right_parts = []
            task_parts = []
            if subagents_active > 0:
                task_parts.append(
                    f"{subagents_active} agent" if subagents_active == 1 else f"{subagents_active} agents"
                )
            if active_bg_tasks > 0:
                task_parts.append(f"{active_bg_tasks} shell")
            if task_parts:
                row3_right_parts.extend(f"[{THEME_SECONDARY}]{p}[/]" for p in task_parts)
            row3_right = "  •  ".join(row3_right_parts)

            grid = Table.grid(expand=True)
            grid.add_column(justify="left")
            grid.add_column(justify="right")
            grid.add_row(row1_left, row1_right)
            grid.add_row(row2_left, row2_right)
            grid.add_row(row3_left, row3_right)
            grid.add_row("", "")

            self._last_grid_rows = [
                (row1_left, row1_right),
                (row2_left, row2_right),
                (row3_left, row3_right),
                ("", ""),
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


class SubagentStatusFooter(GitMetricsMixin, Static):
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

    def _render_stream_frame(self) -> None:
        """Redraw only the animated frame from cached status rows (no git/rebuild)."""
        if not self.is_generating:
            return
        rows = getattr(self, "_last_grid_rows", None)
        if rows is None:
            return
        try:
            frame = SPINNER_FRAMES[self._spinner_idx % len(SPINNER_FRAMES)]
            grid = Table.grid(expand=True)
            grid.add_column(justify="left")
            grid.add_column(justify="right")
            for i, (left, right) in enumerate(rows):
                if i == 0:
                    left = self._swap_frame(left, frame)
                grid.add_row(left, right)
            self.update(grid)
        except Exception:
            pass

    @staticmethod
    def _swap_frame(left: str, frame: str) -> str:
        """Replace the old spinner char in the cached left cell with the new frame."""
        try:
            idx = left.index("]") + 1
            return left[:idx] + frame + left[idx + 1 :]
        except Exception:
            return left

    def _render_footer(self) -> None:
        grid = Table.grid(expand=True)
        grid.add_column(justify="left")
        grid.add_column(justify="right")
        if not self.session:
            grid.add_row("", "")
            grid.add_row("", "")
            grid.add_row("", "")
            self._last_grid_rows = [("", ""), ("", ""), ("", "")]
            self.update(grid)
            return
        session = self.session
        try:
            agent = getattr(session, "agent", None)
            app_agent = getattr(self.app, "agent", None) if self.app else None
            role = getattr(agent, "role", "worker") if agent else getattr(session, "role", "worker")
            effort_val = getattr(agent, "thinking_effort", None) if agent else getattr(app_agent, "thinking_effort", None)
            thinking_effort = display_thinking_effort(effort_val) if effort_val else "auto"
            metrics = agent.get_metrics() if (agent and hasattr(agent, "get_metrics")) else {}
            provider_key = (
                getattr(agent, "provider_key", "")
                if agent
                else (getattr(app_agent, "provider_key", "") if app_agent else "")
            )

            pm = getattr(self.app, "pm", None)
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

            context_limit = (
                metrics.get("context_limit")
                or getattr(agent, "context_limit", None)
                or getattr(app_agent, "context_limit", 128000)
                or 128000
            )
            context_window = metrics.get("context") or format_context_tokens(context_limit)

            role_formatted = f"{SPINNER_FRAMES[self._spinner_idx % len(SPINNER_FRAMES)]} " if self.is_generating else ""
            role_formatted += role.capitalize()

            branch = getattr(session, "branch_name", "") or self._git_branch(cwd=directory)
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
        except Exception:
            pass

    def _on_diff_updated(self) -> None:
        self._render_footer()
