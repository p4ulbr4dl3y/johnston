import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from app import (
    get_version,
    print_mcp,
    print_models,
    print_modes,
    print_rules,
    print_skills,
    print_subagents,
    print_system_prompt,
)


class TestCLI(unittest.TestCase):
    def test_get_version(self):
        ver = get_version()
        self.assertIsInstance(ver, str)
        self.assertTrue(len(ver) > 0)

    def test_print_models(self):
        f = io.StringIO()
        with redirect_stdout(f):
            print_models()
        output = f.getvalue()
        self.assertIn("Available Johnston Providers & Models:", output)

    def test_print_skills(self):
        f = io.StringIO()
        with redirect_stdout(f):
            print_skills()
        output = f.getvalue()
        self.assertIn("Available Johnston Skills:", output)

    def test_print_mcp(self):
        f = io.StringIO()
        with redirect_stdout(f):
            print_mcp()
        output = f.getvalue()
        self.assertIn("Configured MCP Servers:", output)

    @patch("core.mcp_manager.MCPManager.load_servers")
    def test_print_mcp_url_error(self, mock_load):
        mock_load.return_value = [
            {"name": "hf_server", "url": "https://hf.co/mcp", "scope": "global", "mode": "lazy", "disabled": False}
        ]
        f = io.StringIO()
        with redirect_stdout(f):
            print_mcp()
        output = f.getvalue()
        self.assertIn("hf_server", output)
        self.assertIn("URL: https://hf.co/mcp", output)
        self.assertIn("HTTP/SSE URL transport not supported yet", output)

    @patch("core.mcp_manager.MCPManager.load_servers")
    @patch("core.mcp_manager.MCPManager.get_active_tools")
    def test_print_mcp_with_tools(self, mock_tools, mock_load):
        mock_load.return_value = [
            {"name": "my_server", "command": "node server.js", "scope": "project", "mode": "eager", "disabled": False}
        ]
        mock_tools.return_value = [
            {"_mcp_server": "my_server", "_mcp_tool_name": "tool_a"},
            {"_mcp_server": "my_server", "_mcp_tool_name": "tool_b"},
        ]
        f = io.StringIO()
        with redirect_stdout(f):
            print_mcp()
        output = f.getvalue()
        self.assertIn("my_server", output)
        self.assertIn("Tools: tool_a, tool_b", output)

    def test_print_rules(self):
        f = io.StringIO()
        with redirect_stdout(f):
            print_rules()
        output = f.getvalue()
        self.assertIn("Active Rules & Project Instructions:", output)

    def test_print_modes(self):
        f = io.StringIO()
        with redirect_stdout(f):
            print_modes()
        output = f.getvalue()
        self.assertIn("Available Agent Execution Modes:", output)

    def test_print_subagents(self):
        f = io.StringIO()
        with redirect_stdout(f):
            print_subagents()
        output = f.getvalue()
        self.assertIn("Available Subagent Definitions:", output)

    def test_print_system_prompt(self):
        f = io.StringIO()
        with redirect_stdout(f):
            print_system_prompt()
        output = f.getvalue()
        self.assertIn("Primary Goal", output)
        self.assertIn("## Skills", output)
        self.assertIn("## Subagents", output)


if __name__ == "__main__":
    unittest.main()

