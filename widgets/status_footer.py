import os

from rich.table import Table
from textual.widgets import Static

from core.config import THEME_PRIMARY, THEME_SECONDARY, THEME_SUBTLE
from core.models_catalog import format_context_tokens

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
                self._spinner_timer = self.set_interval(0.1, self._spin)
        else:
            if self._spinner_timer:
                self._spinner_timer.stop()
                self._spinner_timer = None
            self._spinner_idx = 0
        self.on_mount()

    def _spin(self) -> None:
        self._spinner_idx = (self._spinner_idx + 1) % len(SPINNER_FRAMES)
        self.on_mount()

    def on_mount(self) -> None:
        try:
            from core.mcp_manager import get_mcp_manager
            from core.skill_manager import SkillManager

            pm = getattr(self.app, "pm", None)
            pkey = pm.get_active_provider_key() if pm else "default"
            agent = getattr(self.app, "agent", None)
            model_name = getattr(agent, "model", "")
            metrics = agent.get_metrics() if (agent and hasattr(agent, "get_metrics")) else {}

            skills_count = len(SkillManager().list_skills())
            mcp_servers = get_mcp_manager().load_servers()
            mcp_total = len(mcp_servers)
            mcp_active = sum(1 for s in mcp_servers if not s.get("disabled", False))
            bg_tasks = getattr(self.app, "background_tasks", [])
            bash_tasks = [t for t in bg_tasks if not getattr(t, "task_id", "").startswith("subagent-")]
            active_bg_tasks = len([t for t in bash_tasks if getattr(t, "is_running", False)])

            subagents = [t for t in bg_tasks if getattr(t, "task_id", "").startswith("subagent-")]
            subagents_active = len([t for t in subagents if getattr(t, "is_running", False)])
            subagents_total = len(subagents)

            agent_mode = getattr(agent, "mode", "action")

            self.update_status(
                provider_key=pkey,
                model_name=model_name,
                agent_mode=agent_mode,
                directory=os.path.basename(os.path.realpath(os.getcwd())),
                active_bg_tasks=active_bg_tasks,
                subagents_active=subagents_active,
                subagents_total=subagents_total,
                context_used=metrics.get("context_used", 0),
                total_tokens=metrics.get("total_tokens", 0),
                context_window=metrics.get("context", "128k"),
                context_limit=metrics.get("context_limit", 128000),
                cost_usd=metrics.get("cost_usd", 0.0),
                skills_count=skills_count,
                mcp_active=mcp_active,
                mcp_total=mcp_total
            )
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
        skills_count: int = 0,
        mcp_active: int = 0,
        mcp_total: int = 0
    ) -> None:
        if not directory:
            directory = os.path.basename(os.path.realpath(os.getcwd())) or "root"

        dir_text = f"~/{directory}"
        pm = getattr(self.app, "pm", None)
        provider_display = provider_key
        if pm:
            providers = pm.load_providers()
            if provider_key in providers:
                provider_display = providers[provider_key].get("name", provider_key)
        elif provider_key:
            provider_display = provider_key.capitalize()

        from core.models_catalog import catalog
        clean_model = catalog.get_model_display_name(provider_key, model_name)
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
            if clean_model:
                row1_left_parts.append(f"[{THEME_SECONDARY}]{clean_model}[/{THEME_SECONDARY}]")
            row1_left = " • ".join(row1_left_parts)
            row1_right = f"[{THEME_SECONDARY}]MCP:{mcp_active}[/{THEME_SECONDARY}]" if mcp_total > 0 else ""

            ctx_val = context_used if context_used > 0 else total_tokens
            pct = (ctx_val / context_limit * 100) if context_limit > 0 else 0.0
            pct = min(100.0, max(0.0, pct))
            pct_str = "0%" if pct == 0 else f"{pct:.0f}%"
            row2_left = f"Ctx: [{THEME_SECONDARY}]{pct_str}[/{THEME_SECONDARY}]"

            row2_right_parts = [f"[{THEME_SECONDARY}]{total_tokens:,}t[/{THEME_SECONDARY}]"]
            if active_bg_tasks > 0:
                row2_right_parts.append(f"[{THEME_SECONDARY}]{active_bg_tasks}bg[/{THEME_SECONDARY}]")
            if subagents_active > 0:
                row2_right_parts.append(f"[{THEME_SECONDARY}]{subagents_active}/{subagents_total}sub[/{THEME_SECONDARY}]")
            row2_right = " • ".join(row2_right_parts)
        else:
            # Line 1: Left (Mode • Project • Provider › Model), Right (Skills • MCP)
            row1_left_parts = [
                f"[bold {THEME_PRIMARY}]{mode_formatted}[/bold {THEME_PRIMARY}]",
                f"[{THEME_SECONDARY}]{dir_text}[/{THEME_SECONDARY}]"
            ]

            if provider_display and clean_model:
                row1_left_parts.append(f"[{THEME_SECONDARY}]{provider_display} › {clean_model}[/{THEME_SECONDARY}]")
            elif provider_display:
                row1_left_parts.append(f"[{THEME_SECONDARY}]{provider_display}[/{THEME_SECONDARY}]")

            row1_left = "  •  ".join(row1_left_parts)

            row1_right_parts = [
                f"Skills: [{THEME_SECONDARY}]{skills_count}[/{THEME_SECONDARY}]",
                f"MCP: [{THEME_SECONDARY}]{mcp_active}/{mcp_total}[/{THEME_SECONDARY}]" if mcp_total > 0 else f"MCP: [{THEME_SECONDARY}]0[/{THEME_SECONDARY}]"
            ]
            row1_right = "  •  ".join(row1_right_parts)

            # Line 2: Left (Context), Right (Tokens • Cost • Activity)
            ctx_val = context_used if context_used > 0 else total_tokens
            pct = (ctx_val / context_limit * 100) if context_limit > 0 else 0.0
            pct = min(100.0, max(0.0, pct))
            bar_len = 8
            filled = int(round((pct / 100) * bar_len))
            bar_str = "█" * filled + "░" * (bar_len - filled)
            used_formatted = format_context_tokens(ctx_val)

            pct_str = "0%" if pct == 0 else f"{pct:.1f}%"
            row2_left = f"Context: [{THEME_SUBTLE}][{bar_str}][/{THEME_SUBTLE}] [{THEME_SECONDARY}]{pct_str} ({used_formatted}/{context_window})[/{THEME_SECONDARY}]"

            cost_str = "$0" if cost_usd == 0 else f"${cost_usd:.4f}"
            row2_right_parts = [
                f"[{THEME_SECONDARY}]{total_tokens:,} tok[/{THEME_SECONDARY}]",
                f"[{THEME_SECONDARY}]{cost_str}[/{THEME_SECONDARY}]"
            ]

            if active_bg_tasks > 0:
                row2_right_parts.append(f"[{THEME_SECONDARY}]{active_bg_tasks} bg task[/{THEME_SECONDARY}]")
            if subagents_active > 0:
                row2_right_parts.append(f"[{THEME_SECONDARY}]{subagents_active}/{subagents_total} subagent[/{THEME_SECONDARY}]")

            row2_right = "  •  ".join(row2_right_parts)

        grid = Table.grid(expand=True)
        grid.add_column(justify="left")
        grid.add_column(justify="right")
        grid.add_row(row1_left, row1_right)
        grid.add_row(row2_left, row2_right)

        self.update(grid)

    def on_resize(self, event) -> None:
        self.on_mount()
