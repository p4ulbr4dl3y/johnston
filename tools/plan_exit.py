from typing import Any, Dict
from tools.base import BaseTool

class PlanExitTool(BaseTool):
    name = "PlanExit"
    description = "Signal that planning phase is complete and request switching to build mode to implement the plan."

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        if app and hasattr(app, "agent"):
            app.agent.mode = "build"
            if hasattr(app, "refresh_status_footer"):
                app.refresh_status_footer()
            if hasattr(app, "notify"):
                app.notify("Mode switched: build")
            return "Switched to build mode. You can now edit files and run implementation commands."
        return "Plan exit tool executed."
