import os

from rich.table import Table
from textual.widgets import Static

from core.config import THEME_PRIMARY, THEME_SECONDARY, THEME_SUBTLE
from core.models_catalog import format_context_tokens


class StatusFooter(Static):
    """Двухстрочная информационная строка состояния под чатом"""
    can_focus = False
    ALLOW_SELECT = False

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

            agent_mode = getattr(agent, "mode", "build")

            self.update_status(
                provider_key=pkey,
                model_name=model_name,
                agent_mode=agent_mode,
                directory=os.path.basename(os.path.realpath(os.getcwd())),
                active_bg_tasks=active_bg_tasks,
                subagents_active=subagents_active,
                subagents_total=subagents_total,
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
        agent_mode: str = "build",
        directory: str = "",
        active_bg_tasks: int = 0,
        subagents_active: int = 0,
        subagents_total: int = 0,
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

        # Строка 1: Окружение и Режим
        dir_text = f"Dir: [{THEME_SECONDARY}]{directory}[/{THEME_SECONDARY}]"
        prov_text = f"Provider: [{THEME_SECONDARY}]{provider_key}[/{THEME_SECONDARY}]" if provider_key else f"Provider: [{THEME_SECONDARY}]default[/{THEME_SECONDARY}]"
        clean_model = model_name.split("/")[-1] if "/" in model_name else model_name
        model_text = f"Model: [{THEME_SECONDARY}]{clean_model}[/{THEME_SECONDARY}]" if clean_model else ""
        left_1_parts = [dir_text, prov_text]
        if model_text:
            left_1_parts.append(model_text)
        left_1 = "  │  ".join(left_1_parts)
        right_1 = f"Mode: [bold {THEME_PRIMARY}][{agent_mode.upper()}][/bold {THEME_PRIMARY}]"

        # Строка 2: Скиллы, MCP и Задачи/Субагенты
        skills_text = f"Skills: [{THEME_SECONDARY}]{skills_count}[/{THEME_SECONDARY}]"
        mcp_text = f"MCP: [{THEME_SECONDARY}]{mcp_active}/{mcp_total} on[/{THEME_SECONDARY}]" if mcp_total > 0 else f"MCP: [{THEME_SECONDARY}]0[/{THEME_SECONDARY}]"
        left_2 = f"{skills_text}  │  {mcp_text}"
        right_2 = f"Tasks: [{THEME_SECONDARY}]{active_bg_tasks} bg[/{THEME_SECONDARY}]  │  Subagents: [{THEME_SECONDARY}]{subagents_active}/{subagents_total}[/{THEME_SECONDARY}]"

        # Строка 3: Прогресс контекста, Токены и Стоимость
        pct = (total_tokens / context_limit * 100) if context_limit > 0 else 0.0
        pct = min(100.0, max(0.0, pct))
        bar_len = 8
        filled = int(round((pct / 100) * bar_len))
        bar_str = "█" * filled + "░" * (bar_len - filled)
        used_formatted = format_context_tokens(total_tokens)
        left_3 = f"Context: [{THEME_SUBTLE}][{bar_str}][/{THEME_SUBTLE}] [{THEME_SECONDARY}]{pct:.1f}% ({used_formatted}/{context_window})[/{THEME_SECONDARY}]"

        tokens_text = f"Tokens: [{THEME_SECONDARY}]{total_tokens:,} tok[/{THEME_SECONDARY}]"
        cost_text = f"Cost: [{THEME_SECONDARY}]${cost_usd:.4f}[/{THEME_SECONDARY}]"
        right_3 = f"{tokens_text}  │  {cost_text}"

        grid = Table.grid(expand=True)
        grid.add_column(justify="left")
        grid.add_column(justify="right")

        grid.add_row(left_1, right_1)
        grid.add_row(left_2, right_2)
        grid.add_row(left_3, right_3)

        self.update(grid)
