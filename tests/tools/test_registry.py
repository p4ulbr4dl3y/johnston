import unittest
from unittest.mock import MagicMock, patch

from tools.registry import REGISTRY, execute_tool, get_default_tools


class TestRegistry(unittest.IsolatedAsyncioTestCase):
    def test_get_default_tools(self):
        tools = get_default_tools()
        self.assertIsInstance(tools, list)
        self.assertTrue(len(tools) > 0)
        for t in tools:
            self.assertIn("type", t)
            self.assertIn("function", t)

    async def test_execute_tool_success_and_alias(self):
        # Execute tool via canonical name
        res = await execute_tool("read", {"path": "nonexistent_abc_123.txt"})
        self.assertIn("ERR:", res)

        # Execute tool via alias
        res_alias = await execute_tool("cat", {"path": "nonexistent_abc_123.txt"})
        self.assertIn("ERR:", res_alias)

        # Test additional aliases resolution
        from tools.registry import ALIAS_MAP
        self.assertEqual(ALIAS_MAP["edit_file"], "edit")
        self.assertEqual(ALIAS_MAP["spawn_subagent"], "invoke_subagent")
        self.assertEqual(ALIAS_MAP["mcp"], "call_mcp")
        self.assertEqual(ALIAS_MAP["fetch"], "web_fetch")

    async def test_execute_tool_execution_exception(self):
        with patch.object(REGISTRY["read"], "execute", side_effect=RuntimeError("Execute failed")):
            res = await execute_tool("read", {"path": "foo.txt"})
            self.assertIn("ERR: execute 'read': Execute failed", res)

    async def test_execute_tool_unknown_with_alias_hint(self):
        # Match that resolves to an alias target
        res = await execute_tool("catx", None)
        self.assertIn("ERR: unknown tool 'catx'", res)
        self.assertIn("Did you mean 'cat' (target: read)?", res)

    async def test_execute_tool_unknown_with_direct_hint(self):
        # Match that maps directly to a registry tool name
        res = await execute_tool("creats", None)
        self.assertIn("ERR: unknown tool 'creats'", res)
        self.assertIn("Did you mean 'create'?", res)
        self.assertNotIn("target:", res)

    async def test_execute_tool_unknown_no_hint(self):
        res = await execute_tool("zzzzzzzzz_unknown", None)
        self.assertEqual(res, "ERR: unknown tool 'zzzzzzzzz_unknown'")

    async def test_execute_tool_mcp_disallowed_in_mode(self):
        mock_mcp_mgr = MagicMock()
        mock_mcp_mgr.get_active_tools.return_value = [{"function": {"name": "mcp_tool_test"}}]
        mock_mcp_mgr.get_capabilities_for_exposed_tool.return_value = None

        mock_mode_def = MagicMock()
        mock_mode_def.name = "plan"
        mock_mode_def.disallowed_tools = ["mcp_tool_test"]

        mock_mode_mgr = MagicMock()
        mock_mode_mgr.get_mode.return_value = mock_mode_def

        with patch("core.mcp_manager.get_mcp_manager", return_value=mock_mcp_mgr), \
             patch("core.mode_manager.ModeManager.get_instance", return_value=mock_mode_mgr):
            mock_app = MagicMock()
            mock_app.mode = "plan"
            res = await execute_tool("mcp_tool_test", {"arg": "val"}, app=mock_app)
            self.assertIn("ERR: tool 'mcp_tool_test' disabled in plan mode", res)

    async def test_execute_tool_mcp_success(self):
        mock_mcp_mgr = MagicMock()
        mock_mcp_mgr.get_active_tools.return_value = []
        mock_mcp_mgr.get_capabilities_for_exposed_tool.return_value = {"server": "s1"}
        mock_mcp_mgr.call_tool.return_value = "MCP Executed Output"

        mock_mode_def = MagicMock()
        mock_mode_def.name = "action"
        mock_mode_def.disallowed_tools = []

        mock_mode_mgr = MagicMock()
        mock_mode_mgr.get_mode.return_value = mock_mode_def

        with patch("core.mcp_manager.get_mcp_manager", return_value=mock_mcp_mgr), \
             patch("core.mode_manager.ModeManager.get_instance", return_value=mock_mode_mgr):
            res = await execute_tool("exposed_mcp_tool", {"foo": "bar"})
            self.assertEqual(res, "MCP Executed Output")
            mock_mcp_mgr.call_tool.assert_called_once_with("exposed_mcp_tool", {"foo": "bar"})

    async def test_execute_tool_mcp_error_exception(self):
        mock_mcp_mgr = MagicMock()
        mock_mcp_mgr.get_active_tools.return_value = [{"function": {"name": "faulty_mcp"}}]
        mock_mcp_mgr.get_capabilities_for_exposed_tool.return_value = None
        mock_mcp_mgr.call_tool.side_effect = RuntimeError("MCP connection failed")

        mock_mode_def = MagicMock()
        mock_mode_def.name = "action"
        mock_mode_def.disallowed_tools = []

        mock_mode_mgr = MagicMock()
        mock_mode_mgr.get_mode.return_value = mock_mode_def

        with patch("core.mcp_manager.get_mcp_manager", return_value=mock_mcp_mgr), \
             patch("core.mode_manager.ModeManager.get_instance", return_value=mock_mode_mgr):
            res = await execute_tool("faulty_mcp", {})
            self.assertIn("ERR: mcp 'faulty_mcp': MCP connection failed", res)

    async def test_execute_tool_mcp_returns_none(self):
        mock_mcp_mgr = MagicMock()
        mock_mcp_mgr.get_active_tools.return_value = [{"function": {"name": "none_mcp"}}]
        mock_mcp_mgr.get_capabilities_for_exposed_tool.return_value = None
        mock_mcp_mgr.call_tool.return_value = None

        mock_mode_def = MagicMock()
        mock_mode_def.name = "action"
        mock_mode_def.disallowed_tools = []

        mock_mode_mgr = MagicMock()
        mock_mode_mgr.get_mode.return_value = mock_mode_def

        with patch("core.mcp_manager.get_mcp_manager", return_value=mock_mcp_mgr), \
             patch("core.mode_manager.ModeManager.get_instance", return_value=mock_mode_mgr):
            res = await execute_tool("none_mcp", {})
            self.assertEqual(res, "ERR: unknown tool 'none_mcp'")


if __name__ == "__main__":
    unittest.main()
