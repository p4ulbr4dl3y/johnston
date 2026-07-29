import json
from typing import Any, Dict, Optional

from tools.base import BaseTool


class GetMCPSchemaTool(BaseTool):
    name = "get_mcp_schema"
    description = (
        "Get the input schema (arguments definition) of a lazy-loaded MCP tool by server name and tool name."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "get_mcp_schema",
            "parameters": {
                "type": "object",
                "properties": {
                    "server": {
                        "type": "string",
                        "description": "Name of the MCP server"
                    },
                    "tool": {
                        "type": "string",
                        "description": "Name of the MCP tool"
                    }
                },
                "required": ["server", "tool"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Optional[Any] = None) -> str:
        server = args.get("server")
        tool = args.get("tool")

        if not server or not tool:
            return "Error: Both 'server' and 'tool' parameters are required."

        from core.mcp_manager import get_mcp_manager
        mcp_mgr = get_mcp_manager()

        schema = mcp_mgr.get_tool_schema(server, tool)
        if schema is not None:
            return json.dumps(schema, indent=2, ensure_ascii=False)

        return f"Error: MCP tool '{tool}' on server '{server}' not found or no schema available."
