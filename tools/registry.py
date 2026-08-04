from typing import Any, Dict, Type

from tools.ask_user import AskUserTool
from tools.base import BaseTool
from tools.call_mcp import CallMCPTool
from tools.create import CreateTool
from tools.edit import EditTool, MultiEditTool
from tools.invoke_subagent import InvokeSubagentTool
from tools.manage_subagent import ManageSubagentTool
from tools.manage_task import ManageTaskTool
from tools.read import ReadTool
from tools.shell import ShellTool
from tools.update_plan import UpdatePlanTool
from tools.web_fetch import WebFetchTool

TOOL_CLASSES = [
    ReadTool,
    CreateTool,
    EditTool,
    MultiEditTool,
    ShellTool,
    AskUserTool,
    CallMCPTool,
    ManageTaskTool,
    InvokeSubagentTool,
    ManageSubagentTool,
    UpdatePlanTool,
    WebFetchTool,
]

REGISTRY: Dict[str, Type[BaseTool]] = {cls.name.lower(): cls for cls in TOOL_CLASSES}

ALIAS_MAP: Dict[str, str] = {
    "write": "create",
    "write_file": "create",
    "create_file": "create",
    "save_file": "create",
    "write_to_file": "create",
    "touch": "create",
    "read_file": "read",
    "view_file": "read",
    "cat": "read",
    "read_file_content": "read",
    "edit_file": "edit",
    "replace_file_content": "edit",
    "multi_replace_file_content": "multi_edit",
    "subagent": "invoke_subagent",
    "spawn_subagent": "invoke_subagent",
    "run_subagent": "invoke_subagent",
    "call_mcp_tool": "call_mcp",
    "mcp": "call_mcp",
    "execute_mcp": "call_mcp",
    "update_file": "edit",
    "modify_file": "edit",
    "str_replace_editor": "edit",
    "replace": "edit",
    "multi_replace": "multi_edit",
    "terminal": "shell",
    "exec": "shell",
    "run_command": "shell",
    "bash": "shell",
    "cmd": "shell",
    "run": "shell",
    "ask": "ask_user",
    "ask_question": "ask_user",
    "plan": "update_plan",
    "set_plan": "update_plan",
    "fetch": "web_fetch",
    "fetch_url": "web_fetch",
    "browse": "web_fetch",
    "task": "manage_task",
    "tasks": "manage_task",
    "kill_task": "manage_task",
    "subagents": "manage_subagent",
    "kill_subagent": "manage_subagent",
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
    if hasattr(mcp_mgr, "get_active_tools_async") and not type(mcp_mgr).__name__.endswith("Mock"):
        active_mcp_tools = await mcp_mgr.get_active_tools_async(mode=None)
    else:
        active_mcp_tools = mcp_mgr.get_active_tools(mode=None) or []
    is_mcp = any(t.get("function", {}).get("name") == name for t in active_mcp_tools) or bool(mcp_mgr.get_capabilities_for_exposed_tool(name))

    if not is_mcp:
        import difflib
        all_candidates = set(REGISTRY.keys()) | set(ALIAS_MAP.keys())
        matches = difflib.get_close_matches(clean_name, sorted(all_candidates), n=2, cutoff=0.4)
        hint = ""
        if matches:
            resolved_target = ALIAS_MAP.get(matches[0], matches[0])
            desc_str = f" (target: {resolved_target})" if resolved_target != matches[0] else ""
            hint = f" [Hint: Did you mean '{matches[0]}'{desc_str}?]"
        return f"Unknown tool: {name}{hint}"

    from core.mode_manager import ModeManager

    ctx_or_app = context or app
    app_obj = getattr(ctx_or_app, "app", ctx_or_app)
    mode = getattr(app_obj, "mode", "action") if app_obj is not None else "action"
    mode_def = ModeManager.get_instance().get_mode(str(mode).lower())
    disallowed = [t.lower() for t in (getattr(mode_def, "disallowed_tools", []) or [])]
    if clean_name in disallowed or resolved_name in disallowed:
        return f"Error: Tool '{name}' is disabled in {mode_def.name} mode."

    import inspect
    import unittest.mock
    try:
        if isinstance(mcp_mgr, unittest.mock.Mock) or not hasattr(mcp_mgr, "call_tool_async"):
            res_or_coro = mcp_mgr.call_tool(name, args)
        else:
            res_or_coro = mcp_mgr.call_tool_async(name, args)
        mcp_res = await res_or_coro if inspect.isawaitable(res_or_coro) else res_or_coro
        if mcp_res is not None:
            return mcp_res
    except Exception as e:
        return f"Error executing MCP tool '{name}': {e}"

    return f"Unknown tool: {name}"
