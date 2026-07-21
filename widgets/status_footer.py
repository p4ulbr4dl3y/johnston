import os
from textual.widgets import Static
from rich.table import Table
from models_dev import format_context_tokens

class StatusFooter(Static):
    """Двухстрочная информационная строка состояния под чатом"""
    can_focus = False
    ALLOW_SELECT = False

    def on_mount(self) -> None:
        try:
            from skill_manager import SkillManager
            from mcp_manager import get_mcp_manager

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
        dir_text = f"Dir: {directory}"
        prov_text = f"Provider: {provider_key}" if provider_key else "Provider: default"
        model_text = f"Model: {model_name}" if model_name else ""
        left_1_parts = [dir_text, prov_text]
        if model_text:
            left_1_parts.append(model_text)
        left_1 = "  │  ".join(left_1_parts)
        right_1 = f"Mode: [{agent_mode.upper()}]"

        # Строка 2: Скиллы, MCP и Задачи/Субагенты
        skills_text = f"Skills: {skills_count}"
        mcp_text = f"MCP: {mcp_active}/{mcp_total} on" if mcp_total > 0 else "MCP: 0"
        left_2 = f"{skills_text}  │  {mcp_text}"
        right_2 = f"Tasks: {active_bg_tasks} bg  │  Subagents: {subagents_active}/{subagents_total}"

        # Строка 3: Прогресс контекста, Токены и Стоимость
        pct = (total_tokens / context_limit * 100) if context_limit > 0 else 0.0
        pct = min(100.0, max(0.0, pct))
        bar_len = 8
        filled = int(round((pct / 100) * bar_len))
        bar_str = "█" * filled + "░" * (bar_len - filled)
        used_formatted = format_context_tokens(total_tokens)
        left_3 = f"Context: [{bar_str}] {pct:.1f}% ({used_formatted}/{context_window})"

        tokens_text = f"Tokens: {total_tokens:,} tok"
        cost_text = f"Cost: ${cost_usd:.4f}"
        right_3 = f"{tokens_text}  │  {cost_text}"

        grid = Table.grid(expand=True)
        grid.add_column(justify="left")
        grid.add_column(justify="right")

        grid.add_row(left_1, right_1)
        grid.add_row(left_2, right_2)
        grid.add_row(left_3, right_3)

        self.update(grid)
