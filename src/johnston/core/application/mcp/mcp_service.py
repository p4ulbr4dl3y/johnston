"""Application-layer MCP service — thin facade over the infrastructure MCP manager.

Absorbs direct ``MCPManager``/``get_mcp_manager`` calls from TUI presentation
code so the screen stays a thin renderer over a stable application interface.
Delegates lifecycle (load/toggle/warmup) to the infrastructure manager without
adding business logic here. Core-only (no Textual imports).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class McpService:
    """Application facade exposing the MCP server lifecycle for the UI."""

    def __init__(self) -> None:
        from johnston.core.infrastructure.mcp import get_mcp_manager

        # Resolved lazily so construction never materializes the default config
        # or warns in tests/debugging paths that only build the facade.
        self._mm = get_mcp_manager()
        # Alias for screen attr compatibility (tests read ``mcp_service.mm``).
        self.mm = self._mm

    def list_servers(self) -> List[Dict[str, Any]]:
        """Return the merged global+project MCP server list."""
        return self._mm.load_servers()

    def toggle_server(self, name: str) -> bool:
        """Toggle a server's enabled state in config; returns the new state."""
        return self._mm.toggle_server(name)

    async def warm_tools(self) -> None:
        """Kick off coalesced background tool warmup across enabled servers."""
        await self._mm.ensure_tools_ready_async()

    def warm_server(self, name: str):
        """Start/refresh one enabled server immediately (UI toggle path)."""
        return self._mm.warm_server_async(name)

    def get_server_status(self, server_name: str) -> Dict[str, Any]:
        """Return the status snapshot for one server (UI rendering)."""
        return self._mm.get_server_status(server_name)

    @staticmethod
    def server_enabled(server: Dict[str, Any]) -> bool:
        """True if a server entry is enabled (absent key means enabled)."""
        from johnston.core.infrastructure.mcp import MCPManager

        return MCPManager.server_enabled(server)

    @property
    def tools_refresh_task(self) -> Optional[Any]:
        """Expose the in-flight warmup task (for UI warmup coalescing)."""
        task = getattr(self._mm, "_tools_refresh_task", None)
        return task


__all__ = ["McpService"]
