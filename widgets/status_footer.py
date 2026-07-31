import os

from rich.table import Table
from textual.widgets import Static

from core.config import THEME_PRIMARY, THEME_SECONDARY, THEME_SUBTLE
from core.models_catalog import format_context_tokens
from core.thinking_effort import display_thinking_effort

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

    def refresh_footer(self) -> None:
        try:
            import time

            from core.mcp_manager import get_mcp_manager
            from core.skill_manager import SkillManager

            pm = getattr(self.app, "pm", None)
            pkey = pm.get_active_provider_key() if pm else "default"
            agent = getattr(self.app, "agent", None)
            model_name = getattr(agent, "model", "")
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

            mcp_total = len(mcp_servers)
            mcp_mgr = get_mcp_manager()
            mcp_active = 0
            for s in mcp_servers:
                if s.get("disabled", False):
                    continue
                s_name = s.get("name")
                cmd = s.get("command")
                url = s.get("url")
                if url and not cmd:
                    continue
                client = mcp_mgr.clients.get(s_name) if hasattr(mcp_mgr, "clients") else None
                if client and getattr(client, "last_error", None):
                    continue
                mcp_active += 1
            bg_tasks = getattr(self.app, "background_tasks", [])
            bash_tasks = [t for t in bg_tasks if not getattr(t, "task_id", "").startswith("subagent-")]
            active_bg_tasks = len([t for t in bash_tasks if getattr(t, "is_running", False)])

            subagents = [t for t in bg_tasks if getattr(t, "task_id", "").startswith("subagent-")]
            subagents_active = len([t for t in subagents if getattr(t, "is_running", False)])
            subagents_total = len(subagents)

            agent_mode = getattr(agent, "mode", "action")

            kwargs = {
                "provider_key": pkey,
                "model_name": model_name,
                "agent_mode": agent_mode,
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
                "mcp_total": mcp_total
            }
            self._last_status_args = kwargs
            self.update_status(**kwargs)
        except Exception:
            self.update_status(provider_key="default")

    def update_status(
        self,
        provider_key: str,
        model_name: str = "",
        agent_mode: str = "action",
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
        mcp_total: int = 0
    ) -> None:
        if not directory:
            directory = os.path.basename(os.path.realpath(os.getcwd())) or "root"

        dir_text = f"~/{directory}"
        pm = getattr(self.app, "pm", None)
        provider_display = provider_key
        is_connected = bool(provider_key)
        if pm:
            providers = pm.load_providers()
            if provider_key in providers:
                provider_display = providers[provider_key].get("name", provider_key)
        elif provider_key:
            provider_display = provider_key.capitalize()

        from core.models_catalog import catalog
        clean_model = catalog.get_model_display_name(provider_key, model_name)
        if not clean_model:
            clean_model = "[Select model: /models]"
        mode_str = agent_mode.capitalize()
        if self.is_generating:
            frame = SPINNER_FRAMES[self._spinner_idx % len(SPINNER_FRAMES)]
            mode_formatted = f"{frame} {mode_str}"
        else:
            mode_formatted = mode_str

        width = self.size.width if (self.size and self.size.width > 0) else (self.app.size.width if (self.app and self.app.size) else 80)
        is_compact = width > 0 and width < 75

        if is_compact:
            row1_left_parts = [
                f"[bold {THEME_PRIMARY}]{mode_formatted}[/bold {THEME_PRIMARY}]",
                f"[{THEME_SECONDARY}]{dir_text}[/{THEME_SECONDARY}]"
            ]
            if is_connected and provider_display and clean_model and clean_model != "[Select model: /models]":
                row1_left_parts.append(f"[{THEME_SECONDARY}]{clean_model}[/{THEME_SECONDARY}]")
            att_count = 0
            try:
                if self.app:
                    from widgets.chat_input import ChatInput
                    chat_input = self.app.query_one("#message-input", ChatInput)
                    att_count = len(getattr(chat_input, "clipboard_attachments", []))
            except Exception:
                pass
            if att_count > 0:
                row1_left_parts.append(f"[{THEME_SECONDARY}]{att_count}att[/{THEME_SECONDARY}]")
            row1_left = " • ".join(row1_left_parts)
            row1_right = f"[{THEME_SECONDARY}]MCP:{mcp_active}[/{THEME_SECONDARY}]" if mcp_total > 0 else ""

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
            if active_bg_tasks > 0:
                row2_right_parts.append(f"[{THEME_SECONDARY}]{active_bg_tasks}bg[/]")
            if subagents_active > 0:
                row2_right_parts.append(f"[{THEME_SECONDARY}]{subagents_active}/{subagents_total}sub[/]")
            row2_right = " • ".join(row2_right_parts)
        else:
            row1_left_parts = [
                f"[bold {THEME_PRIMARY}]{mode_formatted}[/]",
                f"[{THEME_SECONDARY}]{dir_text}[/]"
            ]
            is_connected = pm.is_provider_connected(provider_key) if (pm and provider_key) else False

            if is_connected and provider_display and clean_model and clean_model != "[Select model: /models]":
                row1_left_parts.append(f"[{THEME_SECONDARY}]{provider_display} › {clean_model}[/]")

            att_count = 0
            try:
                if self.app:
                    from widgets.chat_input import ChatInput
                    chat_input = self.app.query_one("#message-input", ChatInput)
                    att_count = len(getattr(chat_input, "clipboard_attachments", []))
            except Exception:
                pass

            if att_count > 0:
                img_s = "s" if att_count > 1 else ""
                row1_left_parts.append(f"[{THEME_SECONDARY}]{att_count} image{img_s} attached[/{THEME_SECONDARY}]")

            row1_left = "  •  ".join(row1_left_parts)

            row1_right_parts = [
                f"Skills: [{THEME_SECONDARY}]{skills_visible}/{skills_total}[/]" if skills_total > 0 else f"Skills: [{THEME_SECONDARY}]0[/]",
                f"MCP: [{THEME_SECONDARY}]{mcp_active}/{mcp_total}[/]" if mcp_total > 0 else f"MCP: [{THEME_SECONDARY}]0[/]"
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

            if active_bg_tasks > 0:
                row2_right_parts.append(f"[{THEME_SECONDARY}]{active_bg_tasks} bg task[/]")
            if subagents_active > 0:
                row2_right_parts.append(f"[{THEME_SECONDARY}]{subagents_active}/{subagents_total} subagent[/]")

            row2_right = "  •  ".join(row2_right_parts)

        grid = Table.grid(expand=True)
        grid.add_column(justify="left")
        grid.add_column(justify="right")
        grid.add_row(row1_left, row1_right)
        if row2_left or row2_right:
            grid.add_row(row2_left, row2_right)

        self.update(grid)

    def on_resize(self, event) -> None:
        self.on_mount()
