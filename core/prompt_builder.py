import os
from typing import List, Dict, Any
from core.skill_manager import SkillManager

PLAN_EXIT_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "PlanExit",
        "description": "Signal that planning phase is complete and request switching to build mode to implement the plan.",
        "parameters": {"type": "object", "properties": {}}
    }
}

TASK_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": "Task",
        "description": "Launch a subagent to perform a task. Use subagent_type='explore' for fast codebase search, or 'general' for multi-step tasks. Set background=true to run asynchronously.",
        "parameters": {
            "type": "object",
            "properties": {
                "prompt": {"type": "string", "description": "Task prompt for the subagent"},
                "description": {"type": "string", "description": "Short (3-5 words) description"},
                "subagent_type": {"type": "string", "description": "Type of subagent ('general' or 'explore')"},
                "background": {"type": "boolean", "description": "Run asynchronously in background"}
            },
            "required": ["prompt", "description"]
        }
    }
}

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

        sys_prompt = self.base_system_prompt
        if skills_snippet:
            sys_prompt = f"{sys_prompt}\n\n{skills_snippet}"
        if mcp_snippet:
            sys_prompt = f"{sys_prompt}\n\n{mcp_snippet}"

        if self.mode == "plan":
            sys_prompt += (
                "\n\n[PLAN MODE ACTIVE]\n"
                "You are in Plan mode. Analyze the codebase, research requirements, and outline a step-by-step implementation plan. "
                "Save your plan in '.tui/plans/plan.md'. Do NOT edit project code files directly while in Plan mode. "
                "When the plan is ready, call the PlanExit tool to propose switching to Build mode."
            )
        else:
            local_plan = os.path.join(os.getcwd(), ".tui", "plans", "plan.md")
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
                all_tools.append(PLAN_EXIT_TOOL_SCHEMA)

        if not any(t.get("function", {}).get("name") in ("Task", "task") for t in all_tools):
            all_tools.append(TASK_TOOL_SCHEMA)

        return all_tools
