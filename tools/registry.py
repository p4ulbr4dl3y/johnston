import asyncio
from typing import Any, Dict, Type

from tools.ask_user import AskUserTool
from tools.base import BaseTool
from tools.bash import BashTool
from tools.call_mcp import CallMCPTool
from tools.create import CreateTool
from tools.edit import EditTool
from tools.glob import GlobTool
from tools.grep import GrepTool
from tools.list_dir import ListDirTool
from tools.manage_task import ManageTaskTool
from tools.read import ReadTool
from tools.skill import SkillTool
from tools.subagent import SubagentTool
from tools.view_image import ViewImageTool

TOOL_CLASSES = [
    ReadTool,
    CreateTool,
    EditTool,
    BashTool,
    GlobTool,
    GrepTool,
    ListDirTool,
    AskUserTool,
    SkillTool,
    CallMCPTool,
    ManageTaskTool,
    SubagentTool,
    ViewImageTool,
]

REGISTRY: Dict[str, Type[BaseTool]] = {cls.name: cls for cls in TOOL_CLASSES}


def get_default_tools() -> list[Dict[str, Any]]:
    return [cls.schema for cls in TOOL_CLASSES if getattr(cls, "schema", None)]

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
    mcp_res = await asyncio.to_thread(get_mcp_manager().call_tool, name, args)
    if mcp_res is not None:
        return mcp_res

    return f"Unknown tool: {name}"
