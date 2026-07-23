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
            "description": "Call a lazy-loaded MCP tool by server name, tool name, and arguments.",
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

        from core.mcp_manager import get_mcp_manager
        mcp_mgr = get_mcp_manager()

        res = mcp_mgr.call_tool(tool_name=tool, arguments=arguments, target_server=server)
        if res is not None:
            return res

        return f"Error: Failed to execute MCP tool '{tool}' on server '{server}'. Server or tool not found."
