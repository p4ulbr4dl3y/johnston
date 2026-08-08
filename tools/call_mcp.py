import inspect
import json
from typing import Any, Dict, Optional

from tools.base import BaseTool, truncate_output


class CallMCPTool(BaseTool):
    name = "call_mcp"
    description = "Execute a lazy-loaded MCP tool by server name, tool name, and arguments."
    schema = {
        "type": "function",
        "function": {
            "name": "call_mcp",
            "parameters": {
                "type": "object",
                "properties": {
                    "server": {"type": "string", "description": "MCP server name"},
                    "tool": {"type": "string", "description": "MCP tool name"},
                    "arguments": {"type": "object", "description": "Tool arguments dict"}
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
            return "ERR: 'server' and 'tool' params required"

        from core.role_registry import RoleRegistry, role_tool_error

        app_obj = getattr(app, "app", app)
        mode = getattr(app_obj, "mode", "act") if app_obj is not None else "act"
        role_def = RoleRegistry.get_instance().get_role(str(mode).lower())
        for target in (f"{server}.{tool}", tool, "call_mcp"):
            policy_err = role_tool_error(role_def, target)
            if policy_err:
                return policy_err

        from core.mcp_manager import get_mcp_manager
        mcp_mgr = get_mcp_manager()

        def _get_schema_hint() -> str:
            try:
                schema = mcp_mgr.get_tool_schema(server, tool)
                if isinstance(schema, dict) and schema:
                    return f"\n\n[Hint: MCP Tool Schema for '{tool}']:\n{json.dumps(schema, indent=2, ensure_ascii=False)}"
            except Exception:
                pass
            return ""

        try:
            if not type(mcp_mgr).__name__.endswith("Mock") and hasattr(mcp_mgr, "call_tool_async"):
                res_or_coro = mcp_mgr.call_tool_async(tool, arguments, target_server=server)
            else:
                res_or_coro = mcp_mgr.call_tool(tool, arguments, target_server=server)
            res = await res_or_coro if inspect.isawaitable(res_or_coro) else res_or_coro
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
            return f"ERR: failed '{server}.{tool}': {e}" + _get_schema_hint()

        return f"ERR: server/tool '{server}.{tool}' not found" + _get_schema_hint()
