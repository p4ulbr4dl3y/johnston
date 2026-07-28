import asyncio
from typing import Any, Dict, Type

from tools.ask_user import AskUserTool
from tools.base import BaseTool
from tools.call_mcp import CallMCPTool
from tools.create import CreateTool
from tools.edit import EditTool, MultiReplaceFileContentTool, ReplaceFileContentTool
from tools.manage_subagent import ManageSubagentTool
from tools.manage_task import ManageTaskTool
from tools.read import ReadTool
from tools.shell import ShellTool
from tools.skill import SkillTool
from tools.subagent import SubagentTool
from tools.update_plan import UpdatePlanTool
from tools.view_image import ViewImageTool
from tools.web_fetch import WebFetchTool

TOOL_CLASSES = [
    ReadTool,
    CreateTool,
    EditTool,
    ReplaceFileContentTool,
    MultiReplaceFileContentTool,
    ShellTool,
    AskUserTool,
    SkillTool,
    CallMCPTool,
    ManageTaskTool,
    SubagentTool,
    ManageSubagentTool,
    UpdatePlanTool,
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
    "str_replace_editor": "replace_file_content",
    "update_file": "edit",
    "modify_file": "edit",
    "replace": "replace_file_content",
    "multi_replace": "multi_replace_file_content",
    "terminal": "shell",
    "exec": "shell",
    "run_command": "shell",
    "ask": "ask_user",
    "plan": "update_plan",
    "set_plan": "update_plan",
}


def get_default_tools() -> list[Dict[str, Any]]:
    return [cls.schema for cls in TOOL_CLASSES if getattr(cls, "schema", None)]

async def execute_tool(name: str, args: dict | None, app: Any = None, context: Any = None) -> str:
    args = args or {}
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
    mcp_mgr = get_mcp_manager()

    # Check if the tool is an active MCP tool
    active_mcp_tools = mcp_mgr.get_active_tools(mode=None)
    is_mcp = any(t.get("function", {}).get("name") == name for t in active_mcp_tools) or bool(mcp_mgr.get_capabilities_for_exposed_tool(name))

    if not is_mcp:
        return f"Unknown tool: {name}"

    from core.mode_manager import ModeManager
    from core.policy import policy_engine

    ctx_or_app = context or app
    app_obj = getattr(ctx_or_app, "app", ctx_or_app)
    mode = getattr(app_obj, "mode", "action") if app_obj is not None else "action"
    mode_def = ModeManager.get_instance().get_mode(str(mode).lower())
    approved = bool(getattr(app_obj, "_johnston_policy_approved", False))
    decision = policy_engine.tool_call_decision(
        name,
        args,
        mode_def,
        approved=approved,
    )
    if not decision.allowed:
        return f"Error: Tool '{name}' blocked by policy: {decision.reason}"

    try:
        mcp_res = await asyncio.to_thread(mcp_mgr.call_tool, name, args)
        if mcp_res is not None:
            return mcp_res
    except Exception as e:
        return f"Error executing MCP tool '{name}': {e}"

    return f"Unknown tool: {name}"
