from typing import Any, Dict
from tools.base import BaseTool

class PlanExitTool(BaseTool):
    name = "PlanExit"
    description = "Signal that planning phase is complete and request switching to build mode to implement the plan."

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        ctx = self._ensure_context(app)
        ctx.set_agent_mode("build")
        return "Switched to build mode. You can now edit files and run implementation commands."
