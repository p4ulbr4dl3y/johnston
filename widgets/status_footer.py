import os

from rich.table import Table
from textual.widgets import Static

from core.domain.defaults.config import THEME_MUTED, THEME_PRIMARY, THEME_SECONDARY, THEME_SUBTLE
from core.infrastructure.runtime.thinking_effort import display_thinking_effort
from core.models_catalog import catalog, format_context_tokens
from widgets.git_metrics_mixin import GitMetricsMixin
from widgets.mixins.resize_debounce import ResizeDebounceMixin
from widgets.mixins.stream_frame import SPINNER_FRAMES, StreamFrameMixin
from widgets.utils.responsive import BREAKPOINT_COMPACT, is_compact_width, resolve_width

STATUS_SEP = f"  [{THEME_MUTED}]•[/]  "
STATUS_SEP_COMPACT = f" [{THEME_MUTED}]•[/] "



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
    sandbox_enabled: bool = True,
    execution_mode: str = "review",
) -> tuple[Table, list[tuple[str, str]]]:
    """Shared subagent-status table builder (2-line layout, with compact support)."""
    grid = Table.grid(expand=True)
    grid.add_column(justify="left")
    grid.add_column(justify="right")

    if is_compact:
        # Row 1 (Compact): Left [Model] | Right [pct% ctx • $0.02 / tok]
        row1_left_parts = []
        if is_connected and clean_model and clean_model != "[Select model: /models]":
            row1_left_parts.append(f"[{THEME_SECONDARY}]{clean_model}[/]")
        row1_left = STATUS_SEP_COMPACT.join(row1_left_parts)

        if is_connected and bool(model_name):
            pct = (context_used / context_limit * 100) if context_limit > 0 else 0.0
            pct = min(100.0, max(0.0, pct))
            pct_str = "0%" if pct == 0 else f"{pct:.0f}%"
            cost_str = "$0" if cost_usd == 0 else f"${cost_usd:.2f}"
            right_val = cost_str if cost_usd > 0 else f"{format_context_tokens(total_tokens)}t"
            row1_right = f"[{THEME_SECONDARY}]{pct_str} ctx[/]{STATUS_SEP_COMPACT}[{THEME_SECONDARY}]{right_val}[/]"
        else:
            row1_right = f"[{THEME_SUBTLE}]Run /connect[/{THEME_SUBTLE}]"

        # Row 2 (Compact): Left [dir • branch (+N/-M) • sb:on • mode] | Right []
        dir_basename = os.path.basename(os.path.abspath(directory)) or directory
        row2_left_parts = [f"[{THEME_SECONDARY}]{dir_basename}[/]"]
        diff_text = git_diff_stats()
        if branch and diff_text:
            row2_left_parts.append(f"[{THEME_PRIMARY}]{branch}[/] [{THEME_SECONDARY}]({diff_text})[/]")
        elif branch:
            row2_left_parts.append(f"[{THEME_PRIMARY}]{branch}[/]")
        elif diff_text:
            row2_left_parts.append(f"[{THEME_SECONDARY}]({diff_text})[/]")
        row2_left_parts.append(f"[{THEME_PRIMARY}]sb:on[/]" if sandbox_enabled else f"[{THEME_MUTED}]sb:off[/]")
        if execution_mode:
            row2_left_parts.append(f"[{THEME_SECONDARY}]{execution_mode}[/]")
        row2_left = STATUS_SEP_COMPACT.join(row2_left_parts)
        row2_right = ""

        grid.add_row(row1_left, row1_right)
        grid.add_row(row2_left, row2_right)
        rows = [
            (row1_left, row1_right),
            (row2_left, row2_right),
        ]
        return grid, rows

    # Full mode
    # Row 1: Left [Provider › Model (effort)] | Right [Context bar • tokens • cost]
    row1_left_parts = []
    if is_connected and provider_display and clean_model and clean_model != "[Select model: /models]":
        model_part = f"{provider_display} › {clean_model}"
        if thinking_effort and thinking_effort != "auto":
            model_part += f" ({thinking_effort})"
        row1_left_parts.append(f"[{THEME_SECONDARY}]{model_part}[/]")
    elif clean_model:
        row1_left_parts.append(f"[{THEME_SECONDARY}]{clean_model}[/]")
    row1_left = STATUS_SEP.join(row1_left_parts)

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
        row1_right = STATUS_SEP.join(row1_right_parts)
    else:
        row1_right = f"[{THEME_SUBTLE}]Run /connect to set up API key.[/{THEME_SUBTLE}]"
    grid.add_row(row1_left, row1_right)

    # Row 2: Left [directory • branch (+N/-M) • sandbox: on • mode] | Right []
    dir_text = format_display_path(directory)
    row2_left_parts = [f"[{THEME_SECONDARY}]{dir_text}[/]"]
    diff_text = git_diff_stats()
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

    row2_right = ""
    grid.add_row(row2_left, row2_right)

    rows = [
        (row1_left, row1_right),
        (row2_left, row2_right),
    ]
    return grid, rows


class StatusFooter(ResizeDebounceMixin, GitMetricsMixin, StreamFrameMixin, Static):
    """Two-line status footer below chat"""

    can_focus = False

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
            # Only the spinner frame changed: redraw cheaply from cached rows
            # instead of rebuilding git/table data on every tick.
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

    def _poll_mcp_refresh(self) -> None:
        """MCP refresh trigger: updates footer when server tool discovery completes."""
        self._on_mcp_event()

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

        width = resolve_width(self)
        is_compact = is_compact_width(width)

        if is_compact:
            branch = self._git_branch(cwd=directory)
            diff_text = self._git_diff_stats(cwd=directory)

            # Row 1 (LLM): ⠋ Action • claude-3.7  <left> | <right> 45% ctx • $0.02
            row1_left_parts = [f"[bold {THEME_PRIMARY}]{role_formatted}[/]"]
            if is_connected and clean_model and clean_model != "[Select model: /models]":
                disp_model = clean_model if len(clean_model) <= 18 else clean_model[:17] + "…"
                row1_left_parts.append(f"[{THEME_SECONDARY}]{disp_model}[/]")
            row1_left = STATUS_SEP_COMPACT.join(row1_left_parts)

            if is_connected and bool(model_name):
                pct = (context_used / context_limit * 100) if context_limit > 0 else 0.0
                pct = min(100.0, max(0.0, pct))
                pct_str = "0%" if pct == 0 else f"{pct:.0f}%"
                cost_str = "$0" if cost_usd == 0 else f"${cost_usd:.2f}"
                right_val = cost_str if cost_usd > 0 else f"{format_context_tokens(total_tokens)}t"
                row1_right = f"[{THEME_SECONDARY}]{pct_str} ctx[/]{STATUS_SEP_COMPACT}[{THEME_SECONDARY}]{right_val}[/]"
            else:
                row1_right = f"[{THEME_SUBTLE}]Run /connect[/{THEME_SUBTLE}]"

            # Row 2 (Env): johnston • main (+3/-1) • sb:on • mode  <left> | <right> ⚡ 2a • 1s
            dir_basename = os.path.basename(os.path.abspath(directory)) or directory
            row2_left_parts = [f"[{THEME_SECONDARY}]{dir_basename}[/]"]
            if branch and diff_text:
                row2_left_parts.append(f"[{THEME_PRIMARY}]{branch}[/] [{THEME_SECONDARY}]({diff_text})[/]")
            elif branch:
                row2_left_parts.append(f"[{THEME_PRIMARY}]{branch}[/]")
            elif diff_text:
                row2_left_parts.append(f"[{THEME_SECONDARY}]({diff_text})[/]")
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

    def render_for_size(self) -> None:
        self.refresh_footer()


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
            if sandbox_val is None:
                sandbox_val = True
            sandbox_enabled = bool(sandbox_val)

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

        if not self.session:
            esc_label = "esc: back" if getattr(self, "from_tasks", False) else "esc: close"
            grid.add_row("", f"[{THEME_MUTED}]{esc_label}[/{THEME_MUTED}]")
            self._last_grid_rows = [("", f"[{THEME_MUTED}]{esc_label}[/{THEME_MUTED}]")]
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

            role_part = f"[bold {THEME_PRIMARY}]{role_formatted}[/]"
            description = (getattr(session, "description", "") or "").strip()
            if description:
                max_desc = max(8, width - len(role_str) - (12 if is_compact else 22))
                if len(description) > max_desc:
                    clean_desc = description[: max_desc - 1] + "…"
                else:
                    clean_desc = description
                role_part += f": [{THEME_SECONDARY}]{clean_desc}[/]"

            row_left = role_part
            esc_label = (
                "esc: back"
                if getattr(self, "from_tasks", False)
                else ("esc" if is_compact else "esc: close")
            )
            row_right = f"[{THEME_MUTED}]{esc_label}[/{THEME_MUTED}]"

            grid.add_row(row_left, row_right)
            self._last_grid_rows = [(row_left, row_right)]
            self.update(grid)
        except Exception:
            pass
