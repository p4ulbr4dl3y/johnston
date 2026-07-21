from typing import Dict, Type, Any
from tools.base import BaseTool
from tools.context import ToolContext
from tools.read import ReadTool
from tools.create import CreateTool
from tools.edit import EditTool
from tools.bash import BashTool
from tools.glob import GlobTool
from tools.grep import GrepTool
from tools.ask_user import AskUserTool
from tools.skill import SkillTool
from tools.manage_task import ManageTaskTool
from tools.plan_exit import PlanExitTool
from tools.task import TaskTool

TOOL_CLASSES = [
    ReadTool,
    CreateTool,
    EditTool,
    BashTool,
    GlobTool,
    GrepTool,
    AskUserTool,
    SkillTool,
    ManageTaskTool,
    PlanExitTool,
    TaskTool,
]

REGISTRY: Dict[str, Type[BaseTool]] = {cls.name: cls for cls in TOOL_CLASSES}

async def execute_tool(name: str, args: dict, app: Any = None, context: Any = None) -> str:
    tool_cls = REGISTRY.get(name)
    if tool_cls:
        try:
            tool_inst = tool_cls()
            ctx = tool_inst._ensure_context(context or app)
            return await tool_inst.execute(args, ctx)
        except Exception as e:
            return f"Error executing tool {name}: {e}"

    from core.mcp_manager import get_mcp_manager
    mcp_res = get_mcp_manager().call_tool(name, args)
    if mcp_res is not None:
        return mcp_res

    return f"Unknown tool: {name}"
