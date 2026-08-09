"""MCP (Model Context Protocol) Manager for Johnston."""

from core.mcp_manager.manager import GLOBAL_MCP_FILE, PROJECT_MCP_FILE, MCPManager, get_mcp_manager
from core.mcp_manager.process_client import MCPProcessClient

__all__ = [
    "MCPProcessClient",
    "MCPManager",
    "get_mcp_manager",
    "GLOBAL_MCP_FILE",
    "PROJECT_MCP_FILE",
]
