import json
import os
import shutil
import tempfile
import unittest

from core.commands import COMMAND_REGISTRY
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

    def test_eager_and_lazy_mcp_servers(self):
        mm = MCPManager(project_dir=self.test_dir)

        class DummyClient:
            def __init__(self, name, tools):
                self.name = name
                self.tools = tools
            def start(self): return True
            def call_tool(self, tool_name, args, **kwargs): return f"executed {self.name}:{tool_name}"

        c1 = DummyClient("eagerServer", [{"name": "eager_tool", "description": "eager desc"}])
        c2 = DummyClient("lazyServer", [{"name": "lazy_tool", "description": "lazy desc"}])
        mm.clients = {"eagerServer": c1, "lazyServer": c2}

        mm.load_servers = lambda: [
            {"name": "eagerServer", "command": "python", "disabled": False, "mode": "eager"},
            {"name": "lazyServer", "command": "python", "disabled": False, "mode": "lazy"}
        ]

        eager_tools = mm.get_active_tools(mode="eager")
        self.assertEqual(len(eager_tools), 1)
        self.assertEqual(eager_tools[0]["function"]["name"], "eager_tool")

        lazy_tools = mm.get_active_tools(mode="lazy")
        self.assertEqual(len(lazy_tools), 1)
        self.assertEqual(lazy_tools[0]["function"]["name"], "lazy_tool")

        all_tools = mm.get_active_tools(mode="all")
        self.assertEqual(len(all_tools), 2)

        snippet = mm.get_system_prompt_snippet()
        self.assertIn("<mcp_servers>", snippet)
        self.assertIn("# lazyServer (Lazy)", snippet)
        self.assertIn("- lazy_tool() — lazy desc", snippet)
        self.assertIn("Available Eager MCP tools", snippet)
        self.assertIn("eager_tool", snippet)

        # Call lazy tool explicitly via call_tool
        res = mm.call_tool("lazy_tool", {}, target_server="lazyServer")
        self.assertEqual(res, "executed lazyServer:lazy_tool")


class TestMCPManagerRegression(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.test_dir)

    def test_disabled_server_tools_are_not_exposed_or_callable(self):
        class DummyClient:
            def __init__(self, name):
                self.name = name
                self.tools = [{"name": "search", "description": "Search", "inputSchema": {"type": "object"}}]

            def call_tool(self, name, args, timeout=None):
                return f"{self.name}:{name}:{args}:{timeout}"

        mm = MCPManager(project_dir=self.test_dir)
        mm.clients = {"enabled": DummyClient("enabled"), "disabled": DummyClient("disabled")}
        mm.load_servers = lambda: [
            {"name": "enabled", "command": "python", "disabled": False, "mode": "eager"},
            {"name": "disabled", "command": "python", "disabled": True, "mode": "eager"},
        ]

        names = [t["function"]["name"] for t in mm.get_active_tools(mode="all")]

        self.assertEqual(names, ["search"])
        self.assertEqual(mm.call_tool("search", {"q": "x"}), "enabled:search:{'q': 'x'}:None")
        self.assertIsNone(mm.call_tool("disabled__search", {"q": "x"}))

    def test_namespaced_capabilities_are_resolved(self):
        mm = MCPManager(project_dir=self.test_dir)
        mm.load_servers = lambda: [
            {
                "name": "serverA",
                "command": "python",
                "disabled": False,
                "capabilities": {"serverA__search": ["network", "read"]},
            }
        ]

        self.assertEqual(mm.get_capabilities_for_exposed_tool("serverA__search"), ["network", "read"])


if __name__ == "__main__":
    unittest.main()
