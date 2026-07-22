import json
import os
import shutil
import tempfile
import unittest

from commands import COMMAND_REGISTRY
from core.mcp_manager import MCPManager


class TestMCPManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)

    def test_global_and_project_mcp_servers(self):
        mm = MCPManager(project_dir=self.test_dir)
        mm.global_file = os.path.join(self.test_dir, "global_mcp.json")

        # Write global MCP server
        with open(mm.global_file, "w", encoding="utf-8") as f:
            json.dump({
                "mcpServers": {
                    "global-server": {
                        "command": "python",
                        "args": ["-m", "mcp_server"],
                        "disabled": False
                    }
                }
            }, f)

        # Write project MCP server
        os.makedirs(os.path.dirname(mm.project_file), exist_ok=True)
        with open(mm.project_file, "w", encoding="utf-8") as f:
            json.dump({
                "mcpServers": {
                    "project-server": {
                        "command": "node",
                        "args": ["server.js"],
                        "disabled": False
                    }
                }
            }, f)

        servers = mm.load_servers()
        names = [s["name"] for s in servers]
        self.assertIn("global-server", names)
        self.assertIn("project-server", names)

        # Test toggle
        state = mm.toggle_server("project-server")
        self.assertFalse(state)  # toggled from False -> True (disabled)

        updated_servers = mm.load_servers()
        p_server = next(s for s in updated_servers if s["name"] == "project-server")
        self.assertTrue(p_server["disabled"])

    def test_mcp_command_registered(self):
        self.assertIn("/mcp", COMMAND_REGISTRY)

    def test_namespacing_and_timeout(self):
        mm = MCPManager(project_dir=self.test_dir)
        # Mock client tools
        class DummyClient:
            def __init__(self, name, tools):
                self.name = name
                self.tools = tools
            def start(self): return True
            def call_tool(self, tool_name, args, **kwargs): return f"result from {self.name}:{tool_name}"

        c1 = DummyClient("serverA", [{"name": "search", "description": "s1"}])
        c2 = DummyClient("serverB", [{"name": "search", "description": "s2"}])
        mm.clients = {"serverA": c1, "serverB": c2}

        # Mock load_servers
        mm.load_servers = lambda: [
            {"name": "serverA", "command": "python", "disabled": False},
            {"name": "serverB", "command": "python", "disabled": False}
        ]

        tools = mm.get_active_tools()
        names = [t["function"]["name"] for t in tools]
        self.assertIn("search", names)
        self.assertIn("serverB__search", names)

        res1 = mm.call_tool("search", {})
        self.assertEqual(res1, "result from serverA:search")

        res2 = mm.call_tool("serverB__search", {})
        self.assertEqual(res2, "result from serverB:search")

if __name__ == "__main__":
    unittest.main()
