import os
import tempfile
import shutil
import unittest
import json
from mcp_manager import MCPManager
from commands import COMMAND_REGISTRY

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

if __name__ == "__main__":
    unittest.main()
