"""Routing of tool/resource/prompt calls to the right MCP client.

Resolves exposed tool names (with collision namespaces) against the active
client registry and applies the configured/default call timeout.
"""

import logging
from typing import Any, Dict, List, Optional, Tuple

from core.domain.defaults.config import DEFAULT_MCP_CALL_TIMEOUT

logger = logging.getLogger(__name__)


class MCPCallRouter:
    """Matches tool/resource/prompt names to clients and executes calls."""

    def __init__(self, manager) -> None:
        self._mgr = manager

    def _resolve_timeout(self, timeout: Optional[float]) -> float:
        if timeout is not None:
            return timeout
        try:
            from core.infrastructure.config.settings import get_settings

            return get_settings().tools.mcp_call_timeout
        except Exception:
            return DEFAULT_MCP_CALL_TIMEOUT

    def _resolve_target_client_and_tool(
        self, tool_name: str, active_tools: List[Dict[str, Any]], target_server: Optional[str] = None
    ) -> Tuple[Optional[Any], Optional[str]]:
        """Match exposed or raw tool_name against active MCP clients."""
        for t in active_tools:
            s_name = t.get("_mcp_server")
            o_name = t.get("_mcp_tool_name")
            if s_name is None or o_name is None:
                continue
            if target_server and s_name != target_server:
                continue
            exposed_name = t.get("function", {}).get("name")
            if exposed_name == tool_name or o_name == tool_name:
                client = self._mgr.clients.get(s_name)
                if client:
                    return client, o_name
        return None, None

    def call_tool(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        target_server: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Optional[str]:
        """Executes an MCP tool call by name across active MCP clients."""
        timeout = self._resolve_timeout(timeout)

        if target_server and target_server in self._mgr.clients:
            client = self._mgr.clients[target_server]
            raw_name = tool_name[len(target_server) + 2 :] if tool_name.startswith(f"{target_server}__") else tool_name
            return client.call_tool(raw_name, arguments, timeout=timeout)

        active_tools = self._mgr.get_active_tools()
        client, o_name = self._resolve_target_client_and_tool(tool_name, active_tools, target_server=target_server)
        if client and o_name:
            return client.call_tool(o_name, arguments, timeout=timeout)
        return None

    async def call_tool_async(
        self,
        tool_name: str,
        arguments: Dict[str, Any],
        target_server: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Optional[str]:
        timeout = self._resolve_timeout(timeout)

        if target_server and target_server in self._mgr.clients:
            client = self._mgr.clients[target_server]
            raw_name = tool_name[len(target_server) + 2 :] if tool_name.startswith(f"{target_server}__") else tool_name
            return await client.call_tool_async(raw_name, arguments, timeout=timeout)

        active_tools = await self._mgr.get_active_tools_async()
        client, o_name = self._resolve_target_client_and_tool(tool_name, active_tools, target_server=target_server)
        if client and o_name:
            return await client.call_tool_async(o_name, arguments, timeout=timeout)
        return None

    # -- resources -------------------------------------------------------------

    async def get_active_resources_async(self, timeout: float = 15.0) -> List[Dict[str, Any]]:
        """Returns all resources discovered across enabled MCP servers."""
        resources: List[Dict[str, Any]] = []
        servers = await self._mgr.load_servers_async()
        for s in servers:
            if not self._mgr.server_enabled(s):
                continue
            name = s["name"]
            await self._mgr._load_server_tools_async(s, timeout=timeout)
            client = self._mgr.clients.get(name)
            if client and hasattr(client, "resources"):
                for r in client.resources:
                    r_copy = dict(r)
                    r_copy["_mcp_server"] = name
                    resources.append(r_copy)
        return resources

    async def read_resource_async(
        self, uri: str, server_name: Optional[str] = None, timeout: float = DEFAULT_MCP_CALL_TIMEOUT
    ) -> Optional[Dict[str, Any]]:
        """Reads an MCP resource by URI across enabled servers or from a target server."""
        if server_name and server_name in self._mgr.clients:
            client = self._mgr.clients[server_name]
            if hasattr(client, "read_resource_async"):
                return await client.read_resource_async(uri, timeout=timeout)

        active_resources = await self.get_active_resources_async(timeout=timeout)
        for r in active_resources:
            if r.get("uri") == uri:
                s_name = r.get("_mcp_server")
                client = self._mgr.clients.get(s_name)
                if client and hasattr(client, "read_resource_async"):
                    return await client.read_resource_async(uri, timeout=timeout)

        for client in self._mgr.clients.values():
            if hasattr(client, "read_resource_async"):
                try:
                    res = await client.read_resource_async(uri, timeout=timeout)
                    if res:
                        return res
                except Exception:
                    pass
        return None

    # -- prompts ----------------------------------------------------------------

    async def get_active_prompts_async(self, timeout: float = 15.0) -> List[Dict[str, Any]]:
        """Returns all prompts discovered across enabled MCP servers."""
        prompts: List[Dict[str, Any]] = []
        servers = await self._mgr.load_servers_async()
        for s in servers:
            if not self._mgr.server_enabled(s):
                continue
            name = s["name"]
            await self._mgr._load_server_tools_async(s, timeout=timeout)
            client = self._mgr.clients.get(name)
            if client and hasattr(client, "prompts"):
                for p in client.prompts:
                    p_copy = dict(p)
                    p_copy["_mcp_server"] = name
                    prompts.append(p_copy)
        return prompts

    async def get_prompt_async(
        self,
        name: str,
        arguments: Optional[Dict[str, str]] = None,
        server_name: Optional[str] = None,
        timeout: float = DEFAULT_MCP_CALL_TIMEOUT,
    ) -> Optional[Dict[str, Any]]:
        """Gets prompt messages by prompt name."""
        if server_name and server_name in self._mgr.clients:
            client = self._mgr.clients[server_name]
            if hasattr(client, "get_prompt_async"):
                return await client.get_prompt_async(name, arguments=arguments, timeout=timeout)

        active_prompts = await self.get_active_prompts_async(timeout=timeout)
        for p in active_prompts:
            if p.get("name") == name:
                s_name = p.get("_mcp_server")
                client = self._mgr.clients.get(s_name)
                if client and hasattr(client, "get_prompt_async"):
                    return await client.get_prompt_async(name, arguments=arguments, timeout=timeout)

        for client in self._mgr.clients.values():
            if hasattr(client, "get_prompt_async"):
                try:
                    res = await client.get_prompt_async(name, arguments=arguments, timeout=timeout)
                    if res:
                        return res
                except Exception:
                    pass
        return None


__all__ = ["MCPCallRouter"]
