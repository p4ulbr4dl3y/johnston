from typing import Any, Dict

from tools.base import BaseTool


class SwitchToActionTool(BaseTool):
    name = "SwitchToAction"
    description = "Switch agent mode from Explore to Action after user explicitly approves proceeding."
    schema = {
        "type": "function",
        "function": {
            "name": "SwitchToAction",
            "description": "Switch agent mode from Explore to Action after user explicitly approves proceeding with implementation/edits.",
            "parameters": {"type": "object", "properties": {}},
        },
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        ctx = self._ensure_context(app)
        ctx.set_agent_mode("action")
        return "Switched to Action mode. Code modification and execution tools are now active."
