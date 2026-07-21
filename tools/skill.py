from typing import Any, Dict

from core.skill_manager import SkillManager
from tools.base import BaseTool


class SkillTool(BaseTool):
    name = "Skill"
    description = (
        "Load a specialized skill when the task matches one of the available skills in system context. "
        "Injects instructions and resources for the specified skill."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "Skill",
            "description": "Load a specialized skill when the task matches one of the available skills in system context.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Skill name to load"}
                },
                "required": ["name"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        skill_name = args.get("name") or args.get("skill")
        if not skill_name:
            return "Error: Missing required parameter 'name'"

        sm = SkillManager()
        return sm.load_skill_payload(skill_name)
