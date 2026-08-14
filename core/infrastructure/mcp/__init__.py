"""MCP (Model Context Protocol) Manager for Johnston."""

from core.infrastructure.mcp.manager import GLOBAL_MCP_FILE, PROJECT_MCP_FILE, MCPManager, get_mcp_manager
from core.infrastructure.mcp.process_client import MCPProcessClient

__all__ = [
    "MCPProcessClient",
    "MCPManager",
    "get_mcp_manager",
    "GLOBAL_MCP_FILE",
    "PROJECT_MCP_FILE",
]
