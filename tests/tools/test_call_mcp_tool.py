import unittest
from unittest.mock import MagicMock, patch

from tools.call_mcp import CallMCPTool


class TestCallMCPTool(unittest.IsolatedAsyncioTestCase):

    async def test_missing_server_param(self):
        tool = CallMCPTool()
        res = await tool.execute({"tool": "some_tool"})
        self.assertIn("Error", res)
        self.assertIn("required", res)

    async def test_missing_tool_param(self):
        tool = CallMCPTool()
        res = await tool.execute({"server": "my_server"})
        self.assertIn("Error", res)
        self.assertIn("required", res)

    async def test_missing_both_params(self):
        tool = CallMCPTool()
        res = await tool.execute({})
        self.assertIn("Error", res)
        self.assertIn("required", res)

    async def test_successful_call(self):
        tool = CallMCPTool()
        mock_mgr = MagicMock()
        mock_mgr.get_tool_capabilities.return_value = ["fs.read"]
        mock_mgr.call_tool.return_value = "MCP tool result text"

        with patch("core.mcp_manager.get_mcp_manager", return_value=mock_mgr):
            res = await tool.execute({"server": "fs", "tool": "read_file", "arguments": {"path": "/tmp"}})

        self.assertEqual(res, "MCP tool result text")
        mock_mgr.call_tool.assert_called_once_with("read_file", {"path": "/tmp"}, target_server="fs")

    async def test_call_returns_none(self):
        tool = CallMCPTool()
        mock_mgr = MagicMock()
        mock_mgr.get_tool_capabilities.return_value = ["fs.read"]
        mock_mgr.call_tool.return_value = None

        with patch("core.mcp_manager.get_mcp_manager", return_value=mock_mgr):
            res = await tool.execute({"server": "fs", "tool": "missing_tool"})

        self.assertIn("Error", res)
        self.assertIn("Failed to execute", res)
        self.assertIn("missing_tool", res)

    async def test_arguments_default_empty(self):
        tool = CallMCPTool()
        mock_mgr = MagicMock()
        mock_mgr.get_tool_capabilities.return_value = ["fs.read"]
        mock_mgr.call_tool.return_value = "ok"

        with patch("core.mcp_manager.get_mcp_manager", return_value=mock_mgr):
            await tool.execute({"server": "srv", "tool": "t"})

        mock_mgr.call_tool.assert_called_once_with("t", {}, target_server="srv")


if __name__ == "__main__":
    unittest.main()
