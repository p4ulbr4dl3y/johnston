import os

from rich.table import Table
from textual.widgets import Static

from core.defaults.config import THEME_PRIMARY, THEME_SECONDARY, THEME_SUBTLE
from core.models_catalog import catalog, format_context_tokens
from core.thinking_effort import display_thinking_effort
from widgets.screens.constants import MESSAGE_INPUT

SPINNER_FRAMES = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]


class StatusFooter(Static):
    """Two-line status footer below chat"""

    can_focus = False
    ALLOW_SELECT = False

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.is_generating: bool = False
        self._spinner_idx: int = 0
        self._spinner_timer = None
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
        if hasattr(self, "_last_status_args"):
            self.update_status(**self._last_status_args)
        else:
            self.refresh_footer()

    def on_mount(self) -> None:
        self.refresh_footer()
        # While MCP servers are still warming up (or their tool counts change),
        # poll so the footer spinner and loaded-server count stay current even
        # when not generating.
        self._mcp_poll_timer = self.set_interval(1.0, self._poll_mcp_refresh)

    def _poll_mcp_refresh(self) -> None:
        try:
            from core.mcp_manager import get_mcp_manager

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
        from core.mcp_manager import get_mcp_manager

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
            import time

            from core.mcp_manager import get_mcp_manager
            from core.skill_manager import SkillManager

            pm = getattr(self.app, "pm", None)
            pkey = pm.get_active_provider_key() if pm else "default"
            agent = getattr(self.app, "agent", None)
            model_name = getattr(agent, "model", "")
            providers = pm.load_providers() if pm else {}
            provider_info = providers.get(pkey, {}) if isinstance(providers, dict) else {}
            provider_display = provider_info.get("name", pkey) if provider_info else pkey
            is_connected = pm.is_provider_connected(pkey, provider_info) if (pm and pkey) else False
            clean_model = catalog.get_model_display_name(pkey, model_name)
            if not clean_model:
                clean_model = "[Select model: /models]"
            if pm and hasattr(pm, "get_provider_thinking_effort"):
                effort_val = pm.get_provider_thinking_effort(pkey, model_name)
            else:
                effort_val = getattr(agent, "thinking_effort", None)
            thinking_effort = display_thinking_effort(effort_val)
            metrics = agent.get_metrics() if (agent and hasattr(agent, "get_metrics")) else {}

            now = time.time()
            if not hasattr(self, "_cached_skills") or (now - getattr(self, "_skills_cache_time", 0) > 5.0):
                all_skills = SkillManager().list_skills(include_hidden=True)
                skills_total = len(all_skills)
                skills_visible = sum(1 for s in all_skills if not s.get("hidden"))
                self._cached_skills = (skills_visible, skills_total)
                self._skills_cache_time = now
            skills_visible, skills_total = getattr(self, "_cached_skills", (0, 0))

            if not hasattr(self, "_cached_mcp_servers") or (now - getattr(self, "_mcp_cache_time", 0) > 5.0):
                self._cached_mcp_servers = get_mcp_manager().load_servers()
                self._mcp_cache_time = now
            mcp_servers = self._cached_mcp_servers

            # Count only servers that are actually loading (enabled, stdio
            # command) and of those, only the ones that finished loading: a
            # running client that discovered tools and has no error. Pending or
            # errored servers don't count, so while loading the footer flips to
            # the spinner.
            mcp_total = 0
            for s in mcp_servers:
                if s.get("url") and not s.get("command"):
                    continue
                mcp_total += 1
            mcp_active = self._active_mcp_count(mcp_servers)
            from core.task_collection import collect_current_tasks

            bg_tasks, sessions = collect_current_tasks(self.app, getattr(self.app, "current_session_id", None))

            active_bg_tasks = len(
                [t for t in bg_tasks if getattr(t, "is_running", False) and getattr(t, "is_background", True)]
            )

            subagents_active = len([s for s in sessions if getattr(s, "status", "") == "running"])
            subagents_total = len(sessions)

            agent_role = getattr(agent, "role", "worker")

            kwargs = {
                "provider_key": pkey,
                "provider_display": provider_display,
                "is_connected": is_connected,
                "model_name": model_name,
                "clean_model": clean_model,
                "agent_role": agent_role,
                "directory": os.path.basename(os.path.realpath(os.getcwd())),
                "active_bg_tasks": active_bg_tasks,
                "subagents_active": subagents_active,
                "subagents_total": subagents_total,
                "context_used": metrics.get("context_used", 0),
                "total_tokens": metrics.get("total_tokens", 0),
                "context_window": metrics.get("context", "128k"),
                "context_limit": metrics.get("context_limit", 128000),
                "cost_usd": metrics.get("cost_usd", 0.0),
                "thinking_effort": thinking_effort,
                "skills_visible": skills_visible,
                "skills_total": skills_total,
                "mcp_active": mcp_active,
                "mcp_total": mcp_total,
            }
            self._last_status_args = kwargs
            self.update_status(**kwargs)
        except Exception:
            self.update_status(provider_key="default")

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
            directory = os.path.basename(os.path.realpath(os.getcwd())) or "root"

        dir_text = f"~/{directory}"
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

        width = (
            self.size.width
            if (self.size and self.size.width > 0)
            else (self.app.size.width if (self.app and self.app.size) else 80)
        )
        is_compact = width > 0 and width < 75

        if is_compact:
            row1_left_parts = [
                f"[bold {THEME_PRIMARY}]{role_formatted}[/bold {THEME_PRIMARY}]",
                f"[{THEME_SECONDARY}]{dir_text}[/{THEME_SECONDARY}]",
            ]
            if is_connected and provider_display and clean_model and clean_model != "[Select model: /models]":
                row1_left_parts.append(f"[{THEME_SECONDARY}]{clean_model}[/{THEME_SECONDARY}]")
            att_count = 0
            try:
                if self.app:
                    from widgets.chat_input import ChatInput

                    chat_input = self.app.query_one(MESSAGE_INPUT, ChatInput)
                    att_count = len(getattr(chat_input, "clipboard_attachments", []))
            except Exception:
                pass
            if att_count > 0:
                row1_left_parts.append(f"[{THEME_SECONDARY}]{att_count}att[/{THEME_SECONDARY}]")
            row1_left = " • ".join(row1_left_parts)
            row1_right = self._mcp_footer_text(mcp_active, mcp_total)

            if is_connected and bool(model_name):
                ctx_val = context_used
                pct = (ctx_val / context_limit * 100) if context_limit > 0 else 0.0
                pct = min(100.0, max(0.0, pct))
                pct_str = "0%" if pct == 0 else f"{pct:.0f}%"
                row2_left = f"Ctx: [{THEME_SECONDARY}]{pct_str}[/]"
                row2_right_parts = [f"[{THEME_SECONDARY}]{total_tokens:,}t[/]"]
            elif is_connected:
                row2_left = f"[{THEME_SUBTLE}]Run /models[/{THEME_SUBTLE}]"
                row2_right_parts = []
            else:
                row2_left = f"[{THEME_SUBTLE}]Run /connect[/{THEME_SUBTLE}]"
                row2_right_parts = []
            task_parts = []
            if subagents_active > 0:
                task_parts.append(f"{subagents_active}agent")
            if active_bg_tasks > 0:
                task_parts.append(f"{active_bg_tasks}shell")
            if task_parts:
                row2_right_parts.append(f"[{THEME_SECONDARY}]{', '.join(task_parts)}[/{THEME_SECONDARY}]")
            row2_right = " • ".join(row2_right_parts)
        else:
            row1_left_parts = [f"[bold {THEME_PRIMARY}]{role_formatted}[/]", f"[{THEME_SECONDARY}]{dir_text}[/]"]
            if is_connected and provider_display and clean_model and clean_model != "[Select model: /models]":
                row1_left_parts.append(f"[{THEME_SECONDARY}]{provider_display} › {clean_model}[/]")

            att_count = 0
            try:
                if self.app:
                    from widgets.chat_input import ChatInput

                    chat_input = self.app.query_one(MESSAGE_INPUT, ChatInput)
                    att_count = len(getattr(chat_input, "clipboard_attachments", []))
            except Exception:
                pass

            if att_count > 0:
                img_s = "s" if att_count > 1 else ""
                row1_left_parts.append(f"[{THEME_SECONDARY}]{att_count} image{img_s} attached[/{THEME_SECONDARY}]")

            row1_left = "  •  ".join(row1_left_parts)

            row1_right_parts = [
                f"Skills: [{THEME_SECONDARY}]{skills_visible}/{skills_total}[/]"
                if skills_total > 0
                else f"Skills: [{THEME_SECONDARY}]0[/]",
                self._mcp_footer_text(mcp_active, mcp_total, prefix="MCP:"),
            ]
            row1_right = "  •  ".join(row1_right_parts)

            # Line 2: Left (Context), Right (Tokens • Cost • Activity)
            if is_connected and bool(model_name):
                ctx_val = context_used
                pct = (ctx_val / context_limit * 100) if context_limit > 0 else 0.0
                pct = min(100.0, max(0.0, pct))
                bar_len = 8
                filled = int(round((pct / 100) * bar_len))
                bar_str = "█" * filled + "░" * (bar_len - filled)
                used_formatted = format_context_tokens(ctx_val)

                pct_str = "0%" if pct == 0 else f"{pct:.1f}%"
                row2_left = f"Context: [{THEME_SUBTLE}][{bar_str}][/] [{THEME_SECONDARY}]{pct_str} ({used_formatted}/{context_window})[/]"

                cost_str = "$0" if cost_usd == 0 else f"${cost_usd:.4f}"
                row2_right_parts = [
                    f"[{THEME_SECONDARY}]{total_tokens:,} tok[/]",
                    f"[{THEME_SECONDARY}]{cost_str}[/]",
                    f"[{THEME_SECONDARY}]effort:{thinking_effort}[/]",
                ]
            elif is_connected:
                row2_left = f"[{THEME_SUBTLE}]Run /models to select a model.[/{THEME_SUBTLE}]"
                row2_right_parts = []
            else:
                row2_left = f"[{THEME_SUBTLE}]Run /connect to set up API key.[/{THEME_SUBTLE}]"
                row2_right_parts = []

            task_parts = []
            if subagents_active > 0:
                task_parts.append(
                    f"{subagents_active} agent" if subagents_active == 1 else f"{subagents_active} agents"
                )
            if active_bg_tasks > 0:
                task_parts.append(f"{active_bg_tasks} shell")
            if task_parts:
                row2_right_parts.append(f"[{THEME_SECONDARY}]{', '.join(task_parts)}[/{THEME_SECONDARY}]")

            row2_right = "  •  ".join(row2_right_parts)

        grid = Table.grid(expand=True)
        grid.add_column(justify="left")
        grid.add_column(justify="right")
        grid.add_row(row1_left, row1_right)
        if row2_left or row2_right:
            grid.add_row(row2_left, row2_right)

        self.update(grid)

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
