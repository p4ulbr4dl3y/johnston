"""MCP (Model Context Protocol) Manager for Johnston."""

from core.infrastructure.mcp.manager import (
    GLOBAL_MCP_FILE,
    PROJECT_MCP_FILE,
    MCPManager,
    _mcp_manager_instance,
    get_mcp_manager,
)
from core.infrastructure.mcp.process_client import MCPProcessClient

__all__ = [
    "MCPProcessClient",
    "MCPManager",
    "get_mcp_manager",
    "GLOBAL_MCP_FILE",
    "PROJECT_MCP_FILE",
]


def mcp_tool_is_known(tool_name: str) -> bool:
    """Return True if ``tool_name`` matches an already-discovered MCP tool.

    Memory-only check (no process spawning). Returns False before the manager
    was ever instantiated so UI layers can call this without side effects
    (e.g. materializing the default config) in tests or early startup.
    """
    if _mcp_manager_instance is None:
        return False
    try:
        mgr = get_mcp_manager()
        cached = mgr.get_cached_tools() if hasattr(mgr, "get_cached_tools") else []
    except Exception:
        return False
    return any(
        isinstance(t, dict) and t.get("function", {}).get("name") == tool_name for t in (cached or [])
    )
