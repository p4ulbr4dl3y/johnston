import json
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch

from tools.get_mcp_schema import GetMCPSchemaTool


class TestGetMCPSchemaTool(IsolatedAsyncioTestCase):
    def test_schema_definition(self):
        tool = GetMCPSchemaTool()
        self.assertEqual(tool.name, "get_mcp_schema")
        self.assertIn("server", tool.schema["function"]["parameters"]["properties"])
        self.assertIn("tool", tool.schema["function"]["parameters"]["properties"])

    async def test_execute_missing_params(self):
        tool = GetMCPSchemaTool()
        res = await tool.execute({})
        self.assertIn("Error: Both 'server' and 'tool' parameters are required.", res)

    async def test_execute_success(self):
        tool = GetMCPSchemaTool()
        mock_schema = {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"]
        }

        class MockMCPManager:
            def get_tool_schema(self, server, tool_name):
                if server == "test_server" and tool_name == "search":
                    return mock_schema
                return None

        with patch("core.mcp_manager.get_mcp_manager", return_value=MockMCPManager()):
            res = await tool.execute({"server": "test_server", "tool": "search"})
            parsed = json.loads(res)
            self.assertEqual(parsed, mock_schema)

            res_not_found = await tool.execute({"server": "test_server", "tool": "unknown"})
            self.assertIn("not found", res_not_found)
