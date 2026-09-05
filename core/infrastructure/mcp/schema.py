from typing import Any, Dict, List, Optional


def format_tool_schema(
    tool: Dict[str, Any], server_name: str, seen_names: Dict[str, str]
) -> Optional[Dict[str, Any]]:
    """Formats tool dict to OpenAI function format and handles name collisions across servers."""
    t_name = tool.get("name")
    if not t_name:
        return None

    exposed_name = t_name
    if t_name in seen_names and seen_names[t_name] != server_name:
        exposed_name = f"{server_name}__{t_name}"
    else:
        seen_names[t_name] = server_name

    return {
        "type": "function",
        "function": {
            "name": exposed_name,
            "description": tool.get("description", ""),
            "parameters": tool.get("inputSchema", {"type": "object", "properties": {}}),
        },
        "_mcp_server": server_name,
        "_mcp_tool_name": t_name,
    }


def get_tool_capabilities(servers: List[Dict[str, Any]], server_name: str, tool_name: str) -> List[str]:
    """Returns configured capabilities for an MCP tool."""
    for server in servers:
        if server.get("name") != server_name:
            continue
        caps_cfg = server.get("capabilities") or {}
        caps = caps_cfg.get(tool_name)
        if caps is None:
            caps = caps_cfg.get(f"{server_name}__{tool_name}")
        if isinstance(caps, list):
            return [str(c) for c in caps if str(c).strip()]
        if isinstance(caps, str) and caps.strip():
            return [caps.strip()]
        return []
    return []


def get_capabilities_for_exposed_tool(servers: List[Dict[str, Any]], exposed_name: str) -> List[str]:
    """Resolves capabilities for exposed tool name across servers."""
    if "__" in exposed_name:
        server_name, tool_name = exposed_name.split("__", 1)
        return get_tool_capabilities(servers, server_name, tool_name)

    matches: List[str] = []
    for server in servers:
        server_name = server.get("name", "")
        caps = get_tool_capabilities(servers, server_name, exposed_name)
        if caps:
            matches.extend(caps)
    return sorted(set(matches))


def format_system_prompt_snippet(cached_tools: List[Dict[str, Any]]) -> str:
    """Returns a prompt snippet listing enabled MCP tools grouped by server."""
    if not cached_tools:
        return ""

    by_server: Dict[str, List[str]] = {}
    for t in cached_tools:
        fn = t.get("function", {})
        server = t.get("_mcp_server", "")
        name = fn.get("name")
        if not name:
            continue
        by_server.setdefault(server, []).append(name)

    from core.infrastructure.runtime.prompt_markdown import format_mcp_servers_markdown

    return format_mcp_servers_markdown(by_server)
