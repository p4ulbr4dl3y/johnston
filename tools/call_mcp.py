import json
from typing import Any, Dict

from tools.base import (
    BaseTool,
    call_mcp_tool,
    check_mcp_role_policy,
    format_tool_error,
    truncate_output,
)


class CallMCPTool(BaseTool):
    name = "call_mcp"
    description = "Execute a lazy-loaded MCP tool by server, tool name, and arguments."
    schema = {
        "type": "function",
        "function": {
            "name": "call_mcp",
            "parameters": {
                "type": "object",
                "properties": {
                    "server": {"type": "string", "description": "MCP server name"},
                    "tool": {"type": "string", "description": "MCP tool name"},
                    "arguments": {"type": "object", "description": "Tool arguments dict"},
                },
                "required": ["server", "tool"],
            },
        },
    }

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> str:
        server = args.get("server")
        tool = args.get("tool")
        arguments = args.get("arguments") or {}

        if not server or not tool:
            return format_tool_error("params", name="server.tool", detail="required")

        from core.mcp_manager import get_mcp_manager

        mcp_mgr = get_mcp_manager()

        policy_err = check_mcp_role_policy(ctx, tool, [f"{server}.{tool}", tool, "call_mcp"])
        if policy_err:
            return policy_err

        def _get_schema_hint() -> str:
            try:
                schema = mcp_mgr.get_tool_schema(server, tool)
                if isinstance(schema, dict) and schema:
                    return (
                        f"\n\n[Hint: MCP Tool Schema for '{tool}']:\n{json.dumps(schema, indent=2, ensure_ascii=False)}"
                    )
            except Exception:
                pass
            return ""

        try:
            res = await call_mcp_tool(mcp_mgr, tool, arguments, target_server=server)
            if res is not None:
                if isinstance(res, str) and (res.startswith("Error") or res.lower().startswith("error")):
                    return res + _get_schema_hint()
                text_res = res if isinstance(res, str) else json.dumps(res, ensure_ascii=False)
                return truncate_output(
                    text_res,
                    max_chars=8000,
                    hint="Refine parameters or request partial data if complete response is needed.",
                    tool_name=f"mcp_{tool}",
                )
        except Exception as e:
            return format_tool_error("mcp", detail=str(e), name=f"{server}.{tool}") + _get_schema_hint()

        return format_tool_error("notfound", name=f"{server}.{tool}") + _get_schema_hint()
