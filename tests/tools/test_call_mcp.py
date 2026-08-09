import unittest
from unittest.mock import MagicMock, patch

from tools.call_mcp import CallMCPTool


class TestCallMCPTool(unittest.IsolatedAsyncioTestCase):

    async def test_missing_server_param(self):
        tool = CallMCPTool()
        res = await tool.execute({"tool": "some_tool"})
        self.assertIn("ERR", res)
        self.assertIn("required", res)

    async def test_missing_tool_param(self):
        tool = CallMCPTool()
        res = await tool.execute({"server": "my_server"})
        self.assertIn("ERR", res)
        self.assertIn("required", res)

    async def test_missing_both_params(self):
        tool = CallMCPTool()
        res = await tool.execute({})
        self.assertIn("ERR", res)
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

        self.assertIn("ERR", res)
        self.assertIn("ERR: notfound", res)
        self.assertIn("missing_tool", res)

    async def test_arguments_default_empty(self):
        tool = CallMCPTool()
        mock_mgr = MagicMock()
        mock_mgr.get_tool_capabilities.return_value = ["fs.read"]
        mock_mgr.call_tool.return_value = "ok"

        with patch("core.mcp_manager.get_mcp_manager", return_value=mock_mgr):
            await tool.execute({"server": "srv", "tool": "t"})

        mock_mgr.call_tool.assert_called_once_with("t", {}, target_server="srv")

    async def test_call_error_returns_schema_hint(self):
        tool = CallMCPTool()
        mock_mgr = MagicMock()
        mock_mgr.call_tool.return_value = "Error: Invalid arguments"
        mock_mgr.get_tool_schema.return_value = {"type": "object", "properties": {"path": {"type": "string"}}}

        with patch("core.mcp_manager.get_mcp_manager", return_value=mock_mgr):
            res = await tool.execute({"server": "fs", "tool": "read_file"})

        self.assertIn("Error: Invalid arguments", res)
        self.assertIn("[Hint: MCP Tool Schema for 'read_file']", res)
        self.assertIn('"path"', res)

    async def test_call_truncates_large_output(self):
        tool = CallMCPTool()
        mock_mgr = MagicMock()
        mock_mgr.call_tool.return_value = "x" * 10000

        with patch("core.mcp_manager.get_mcp_manager", return_value=mock_mgr):
            res = await tool.execute({"server": "srv", "tool": "big_data"})

        self.assertIn("Output truncated at 8000 chars", res)
        self.assertTrue(res.startswith("x" * 8000))


if __name__ == "__main__":
    unittest.main()

