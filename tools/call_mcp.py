import asyncio
from typing import Any, Dict, Optional

from tools.base import BaseTool


class CallMCPTool(BaseTool):
    name = "call_mcp_tool"
    description = (
        "Call a lazy-loaded MCP tool by server name, tool name, and arguments. "
        "Use this tool when executing MCP tools listed under lazy MCP servers."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "call_mcp_tool",
            "parameters": {
                "type": "object",
                "properties": {
                    "server": {
                        "type": "string",
                        "description": "Name of the MCP server"
                    },
                    "tool": {
                        "type": "string",
                        "description": "Name of the MCP tool to execute"
                    },
                    "arguments": {
                        "type": "object",
                        "description": "Arguments dictionary for the MCP tool"
                    }
                },
                "required": ["server", "tool"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Optional[Any] = None) -> str:
        server = args.get("server")
        tool = args.get("tool")
        arguments = args.get("arguments") or {}

        if not server or not tool:
            return "Error: Both 'server' and 'tool' parameters are required."
        from core.mode_manager import ModeManager

        app_obj = getattr(app, "app", app)
        mode = getattr(app_obj, "mode", "action") if app_obj is not None else "action"
        mode_def = ModeManager.get_instance().get_mode(str(mode).lower())
        disallowed = [t.lower() for t in (getattr(mode_def, "disallowed_tools", []) or [])]
        if "call_mcp_tool" in disallowed or tool.lower() in disallowed or f"{server}.{tool}".lower() in disallowed:
            return f"Error: MCP tool '{server}.{tool}' is disabled in {mode_def.name} mode."

        from core.mcp_manager import get_mcp_manager
        mcp_mgr = get_mcp_manager()

        try:
            res = await asyncio.to_thread(mcp_mgr.call_tool, tool, arguments, target_server=server)
            if res is not None:
                return res
        except Exception as e:
            return f"Error: Failed to execute MCP tool '{tool}' on server '{server}': {e}"

        return f"Error: Failed to execute MCP tool '{tool}' on server '{server}'. Server or tool not found."
