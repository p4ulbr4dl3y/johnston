"""OpenAI-format tool catalog built from discovered MCP clients.

Naming/formatting happens here, sequentially in config order, so the winner of
a name collision across servers is deterministic (config order), not whatever
concurrent warmup scheduling happened to finish first.
"""

import asyncio
import logging
from typing import Any, Dict, List

from core.infrastructure.mcp.schema import format_system_prompt_snippet, format_tool_schema

logger = logging.getLogger(__name__)


class MCPToolCatalog:
    """Formats raw client tools into OpenAI functions, resolving collisions."""

    def __init__(self, manager) -> None:
        self._mgr = manager

    @staticmethod
    def server_enabled(server: Dict[str, Any]) -> bool:
        return bool(server.get("enabled", True))

    def _eligible(self, servers: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Enabled servers that have a runnable command or url."""
        return [s for s in servers if self.server_enabled(s) and (s.get("command") or s.get("url"))]

    def get_active_tools(self) -> List[Dict[str, Any]]:
        """Sync discovery: connects to enabled servers and returns their tools."""
        tools: List[Dict[str, Any]] = []
        seen_names: Dict[str, str] = {}  # tool_name -> server_name
        for s in self._eligible(self._mgr.load_servers()):
            name = s["name"]
            client = self._mgr.clients.get(name)
            if not client:
                client = self._mgr._create_client(s)
                if client.start():
                    self._mgr.clients[name] = client
                    self._mgr._server_errors.pop(name, None)
                else:
                    err = getattr(client, "last_error", None)
                    if err:
                        self._mgr._server_errors[name] = err
                    continue
            else:
                if self._mgr._tools_fetch_stale(name):
                    try:
                        client.fetch_tools()
                    except Exception:
                        logger.warning("Failed to fetch tools for MCP server %s", name, exc_info=True)

            for t in getattr(client, "tools", []):
                formatted = format_tool_schema(t, name, seen_names)
                if formatted:
                    tools.append(formatted)
        return tools

    async def get_active_tools_async(self) -> List[Dict[str, Any]]:
        """Async discovery: starts every server concurrently, per-server deadline."""
        servers = await self._mgr.load_servers_async()
        eligible = self._eligible(servers)
        # Start every server concurrently with an isolated per-server deadline so
        # a slow/cold (npx/uvx) or broken server cannot stall the others. Tool
        # naming/formatting happens afterwards, sequentially in config order, so
        # the winner of a name collision is deterministic (config order), not
        # whatever gather scheduling happened to finish first.
        results = await asyncio.gather(
            *(self._mgr._load_server_tools_async(s) for s in eligible), return_exceptions=True
        )

        tools: List[Dict[str, Any]] = []
        seen_names: Dict[str, str] = {}
        for server, res in zip(eligible, results):
            if isinstance(res, Exception):
                logger.debug("MCP server %s failed to load tools: %s", server.get("name"), res)
                continue
            for t in res or []:
                formatted = format_tool_schema(t, server["name"], seen_names)
                if formatted:
                    tools.append(formatted)
        return tools

    def get_cached_tools(self) -> List[Dict[str, Any]]:
        """Return already discovered tools without starting processes or I/O."""
        tools: List[Dict[str, Any]] = []
        seen_names: Dict[str, str] = {}
        for server in self._eligible(self._mgr.load_servers()):
            server_name = server.get("name", "")
            client = self._mgr.clients.get(server_name)
            if client is None:
                continue
            for tool in client.tools:
                formatted = format_tool_schema(tool, server_name, seen_names)
                if formatted:
                    tools.append(formatted)
        return tools

    def get_system_prompt_snippet(self) -> str:
        return format_system_prompt_snippet(self.get_cached_tools())


__all__ = ["MCPToolCatalog"]
