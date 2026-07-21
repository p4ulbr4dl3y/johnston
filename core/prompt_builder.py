import os
from typing import Any, Dict, List

from core.skill_manager import SkillManager
from tools.plan_exit import PlanExitTool
from tools.task import TaskTool


class PromptBuilder:
    """Формирует скомпонованный системный промпт и набор инструментов с учетом MCP, Skills и режима (Plan/Build)"""

    def __init__(self, base_system_prompt: str, base_tools: List[Dict[str, Any]], mode: str = "build"):
        self.base_system_prompt = base_system_prompt
        self.base_tools = list(base_tools or [])
        self.mode = mode

    def build_system_prompt(self) -> str:
        from core.mcp_manager import get_mcp_manager
        mcp_mgr = get_mcp_manager()
        mcp_snippet = mcp_mgr.get_system_prompt_snippet()
        skills_snippet = SkillManager().get_system_prompt_snippet()

        sys_prompt = f"{self.base_system_prompt}\n\nCurrent working directory: {os.getcwd()}"
        if skills_snippet:
            sys_prompt = f"{sys_prompt}\n\n{skills_snippet}"
        if mcp_snippet:
            sys_prompt = f"{sys_prompt}\n\n{mcp_snippet}"

        if self.mode == "plan":
            sys_prompt += (
                "\n\n[PLAN MODE ACTIVE]\n"
                "You are in Plan mode. Analyze the codebase, research requirements, and outline a step-by-step implementation plan. "
                "Save your plan in '.johnston/plans/plan.md'. Do NOT edit project code files directly while in Plan mode. "
                "When the plan is ready, call the PlanExit tool to propose switching to Build mode."
            )
        else:
            local_plan = os.path.join(os.getcwd(), ".johnston", "plans", "plan.md")
            if os.path.exists(local_plan):
                sys_prompt += f"\n\n[BUILD MODE ACTIVE]\nA plan file exists at '{local_plan}'. Execute the implementation steps defined within it."

        return sys_prompt

    def build_tools(self) -> List[Dict[str, Any]]:
        from core.mcp_manager import get_mcp_manager
        mcp_tools = get_mcp_manager().get_active_tools()
        clean_mcp_tools = [
            {"type": t["type"], "function": t["function"]} for t in mcp_tools
        ]

        all_tools = list(self.base_tools) + clean_mcp_tools

        if self.mode == "plan":
            if not any(t.get("function", {}).get("name") == "PlanExit" for t in all_tools):
                all_tools.append(PlanExitTool.schema)

        if not any(t.get("function", {}).get("name") in ("Task", "task") for t in all_tools):
            all_tools.append(TaskTool.schema)

        return all_tools
