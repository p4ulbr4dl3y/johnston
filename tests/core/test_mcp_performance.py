import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.mcp_manager import MCPManager
from core.prompt_builder import PromptBuilder


class TestMCPPerformance(unittest.IsolatedAsyncioTestCase):
    def _manager_without_init(self) -> MCPManager:
        manager = MCPManager.__new__(MCPManager)
        manager.clients = {}
        manager._tools_refresh_time = 0.0
        manager._tools_refresh_task = None
        return manager

    def test_system_prompt_uses_cached_tools_without_sync_refresh(self):
        manager = self._manager_without_init()
        manager.load_servers = MagicMock(
            return_value=[
                {"name": "docs", "mode": "lazy", "command": "docs-server"},
            ]
        )
        manager.clients["docs"] = MagicMock(
            tools=[
                {
                    "name": "search",
                    "description": "Search docs",
                    "inputSchema": {"type": "object", "properties": {"query": {"type": "string"}}},
                }
            ]
        )
        manager.get_active_tools = MagicMock(side_effect=AssertionError("sync MCP refresh is forbidden"))

        snippet = manager.get_system_prompt_snippet()

        self.assertIn("docs (Lazy)", snippet)
        self.assertIn("search(query)", snippet)
        manager.get_active_tools.assert_not_called()

    async def test_concurrent_async_refreshes_are_coalesced(self):
        manager = self._manager_without_init()

        release = asyncio.Event()

        async def slow_refresh(mode="eager"):
            await release.wait()
            return [{"type": "function", "function": {"name": "search"}}]

        manager.get_active_tools_async = AsyncMock(side_effect=slow_refresh)

        async def _gather():
            return await asyncio.gather(
                manager.ensure_tools_ready_async(),
                manager.ensure_tools_ready_async(),
            )

        gather_task = asyncio.create_task(_gather())
        # Cooperative yield so the first caller starts its refresh and the second
        # caller joins the shared in-flight refresh task before we release it.
        await asyncio.sleep(0)
        release.set()
        results = await gather_task

        self.assertEqual(results[0], results[1])
        manager.get_active_tools_async.assert_awaited_once_with(mode="eager")

    async def test_recent_refresh_uses_memory_cache(self):
        manager = self._manager_without_init()
        manager._tools_refresh_time = time.monotonic()
        manager.get_cached_tools = MagicMock(return_value=[{"type": "function"}])
        manager.get_active_tools_async = AsyncMock()

        tools = await manager.ensure_tools_ready_async()

        self.assertEqual(tools, [{"type": "function"}])
        manager.get_active_tools_async.assert_not_awaited()

    def test_prompt_builder_never_calls_sync_mcp_discovery(self):
        manager = MagicMock()
        manager.get_system_prompt_snippet.return_value = ""
        manager.get_cached_tools.return_value = []
        manager.get_active_tools.side_effect = AssertionError("sync MCP discovery is forbidden")

        with patch("core.mcp_manager.get_mcp_manager", return_value=manager):
            builder = PromptBuilder("system", [], mode="action")
            builder.build_system_prompt()
            builder.build_tools()

        manager.get_cached_tools.assert_called_once()
        manager.get_active_tools.assert_not_called()
