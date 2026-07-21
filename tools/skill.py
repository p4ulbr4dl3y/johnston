from typing import Any, Dict
from tools.base import BaseTool
from skill_manager import SkillManager

class SkillTool(BaseTool):
    name = "Skill"
    description = (
        "Load a specialized skill when the task matches one of the available skills in system context. "
        "Injects instructions and resources for the specified skill."
    )

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        skill_name = args.get("name") or args.get("skill")
        if not skill_name:
            return "Error: Missing required parameter 'name'"

        sm = SkillManager()
        return sm.load_skill_payload(skill_name)
