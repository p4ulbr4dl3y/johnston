import asyncio
from typing import Any, Dict, Type

from tools.ask_user import AskUserTool
from tools.base import BaseTool
from tools.bash import BashTool
from tools.call_mcp import CallMCPTool
from tools.create import CreateTool
from tools.edit import EditTool
from tools.manage_subagent import ManageSubagentTool
from tools.manage_task import ManageTaskTool
from tools.read import ReadTool
from tools.skill import SkillTool
from tools.subagent import SubagentTool
from tools.view_image import ViewImageTool
from tools.web_fetch import WebFetchTool

TOOL_CLASSES = [
    ReadTool,
    CreateTool,
    EditTool,
    BashTool,
    AskUserTool,
    SkillTool,
    CallMCPTool,
    ManageTaskTool,
    SubagentTool,
    ManageSubagentTool,
    ViewImageTool,
    WebFetchTool,
]

REGISTRY: Dict[str, Type[BaseTool]] = {cls.name.lower(): cls for cls in TOOL_CLASSES}

ALIAS_MAP: Dict[str, str] = {
    "write": "create",
    "write_file": "create",
    "create_file": "create",
    "save_file": "create",
    "read_file": "read",
    "view_file": "read",
    "cat": "read",
    "str_replace_editor": "edit",
    "update_file": "edit",
    "modify_file": "edit",
    "shell": "bash",
    "terminal": "bash",
    "exec": "bash",
    "run_command": "bash",
    "ask": "ask_user",
}


def get_default_tools() -> list[Dict[str, Any]]:
    return [cls.schema for cls in TOOL_CLASSES if getattr(cls, "schema", None)]

async def execute_tool(name: str, args: dict, app: Any = None, context: Any = None) -> str:
    raw_name = (name or "").strip()
    clean_name = raw_name.lower()
    resolved_name = ALIAS_MAP.get(clean_name, clean_name)

    tool_cls = REGISTRY.get(resolved_name) or REGISTRY.get(clean_name)
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
