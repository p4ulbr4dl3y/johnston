from typing import Dict, Type
from tools.base import BaseTool
from tools.read import ReadTool
from tools.create import CreateTool
from tools.edit import EditTool
from tools.bash import BashTool
from tools.glob import GlobTool
from tools.grep import GrepTool
from tools.ask_user import AskUserTool
from tools.skill import SkillTool

TOOL_CLASSES = [
    ReadTool,
    CreateTool,
    EditTool,
    BashTool,
    GlobTool,
    GrepTool,
    AskUserTool,
    SkillTool,
]

REGISTRY: Dict[str, Type[BaseTool]] = {cls.name: cls for cls in TOOL_CLASSES}

async def execute_tool(name: str, args: dict, app=None) -> str:
    tool_cls = REGISTRY.get(name)
    if tool_cls:
        try:
            tool_inst = tool_cls()
            return await tool_inst.execute(args, app)
        except Exception as e:
            return f"Error executing tool {name}: {e}"

    from mcp_manager import MCPManager
    mcp_res = MCPManager().call_tool(name, args)
    if mcp_res is not None:
        return mcp_res

    return f"Unknown tool: {name}"
