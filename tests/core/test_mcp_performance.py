import asyncio
import time
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.application.generation.prompt_builder import PromptBuilder
from core.infrastructure.mcp import MCPManager


class TestMCPPerformance(unittest.IsolatedAsyncioTestCase):
    def _manager_without_init(self) -> MCPManager:
        manager = MCPManager.__new__(MCPManager)
        manager.project_dir = "/"
        manager.project_file = "/.johnston/mcp.json"
        manager.global_file = "/tmp/mcp.json"
        manager.clients = {}
        manager._tools_refresh_time = 0.0
        manager._tools_refresh_task = None
        return manager

    def test_system_prompt_uses_cached_tools_without_sync_refresh(self):
        manager = self._manager_without_init()
        manager.load_servers = MagicMock(
            return_value=[
                {"name": "docs", "command": "docs-server"},
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

        self.assertIn("## MCP Tools", snippet)
        self.assertIn("- docs: search", snippet)
        manager.get_active_tools.assert_not_called()

    async def test_concurrent_async_refreshes_are_coalesced(self):
        manager = self._manager_without_init()
        manager.get_cached_tools = MagicMock(return_value=[])

        release = asyncio.Event()

        async def slow_refresh():
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

        # Both callers share one in-flight warmup and return the same cached view
        # instead of each spawning their own refresh.
        self.assertEqual(list(results), [[], []])
        manager.get_active_tools_async.assert_awaited_once()

    async def test_recent_inflight_refresh_uses_memory_cache(self):
        manager = self._manager_without_init()
        manager._tools_refresh_time = time.monotonic()
        manager.get_cached_tools = MagicMock(return_value=[{"type": "function"}])
        manager.get_active_tools_async = AsyncMock()

        # A warmup task already in flight within the freshness window: return the
        # cached tools and never spawn a second refresh.
        in_flight = asyncio.create_task(asyncio.sleep(10))
        manager._tools_refresh_task = in_flight

        try:
            tools = await manager.ensure_tools_ready_async()
            self.assertEqual(tools, [{"type": "function"}])
            manager.get_active_tools_async.assert_not_awaited()
        finally:
            in_flight.cancel()

    async def test_no_inflight_refresh_spawns_background_without_blocking(self):
        manager = self._manager_without_init()
        manager.get_cached_tools = MagicMock(return_value=[])
        manager.get_active_tools_async = AsyncMock(return_value=[{"type": "function", "function": {"name": "search"}}])

        # No task in flight: spawn a background warmup and return cached (empty)
        # immediately instead of blocking on the cold start.
        tools = await manager.ensure_tools_ready_async()

        # Give the spawned background task a chance to actually run so the
        # assertion below sees the awaited call.
        await asyncio.sleep(0)

        self.assertEqual(tools, [])
        manager.get_active_tools_async.assert_awaited_once()
        self.assertIsInstance(manager._tools_refresh_task, asyncio.Task)
    def test_prompt_builder_never_calls_sync_mcp_discovery(self):
        manager = MagicMock()
        manager.get_system_prompt_snippet.return_value = ""
        manager.get_cached_tools.return_value = []
        manager.get_active_tools.side_effect = AssertionError("sync MCP discovery is forbidden")

        with patch("core.infrastructure.mcp.get_mcp_manager", return_value=manager):
            builder = PromptBuilder("system", [], role="action")
            builder.build_system_prompt()
            builder.build_tools()

        manager.get_cached_tools.assert_called_once()
        manager.get_active_tools.assert_not_called()
