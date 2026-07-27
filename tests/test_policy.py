import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.base_provider import BaseAgent
from core.mode_manager import ModeManager
from core.policy import (
    policy_engine,
    resolve_workspace_path,
    shell_command_is_read_only,
)
from core.prompt_builder import PromptBuilder
from tools.registry import get_default_tools


class TestPolicyEngine(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.old_cwd = os.getcwd()
        os.chdir(self.tmp.name)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.tmp.cleanup()

    def test_workspace_path_blocks_parent_escape(self):
        with self.assertRaises(PermissionError):
            resolve_workspace_path("../outside.txt")

    def test_workspace_path_blocks_symlink_escape(self):
        outside_dir = tempfile.TemporaryDirectory()
        self.addCleanup(outside_dir.cleanup)
        outside_file = os.path.join(outside_dir.name, "secret.txt")
        with open(outside_file, "w", encoding="utf-8") as f:
            f.write("secret")
        os.symlink(outside_file, "link.txt")

        with self.assertRaises(PermissionError):
            resolve_workspace_path("link.txt")

    def test_explore_blocks_write_alias(self):
        mode_def = ModeManager.get_instance().get_mode("explore")
        decision = policy_engine.tool_call_decision(
            "write_file",
            {"path": "x.txt", "content": "x"},
            mode_def,
        )

        self.assertFalse(decision.allowed)
        self.assertIn("disabled", decision.reason)

    def test_explore_allows_read_only_shell(self):
        mode_def = ModeManager.get_instance().get_mode("explore")
        decision = policy_engine.tool_call_decision(
            "shell",
            {"command": "rg policy core tests"},
            mode_def,
        )

        self.assertTrue(decision.allowed)

    def test_action_shell_destructive_requires_approval(self):
        mode_def = ModeManager.get_instance().get_mode("action")
        decision = policy_engine.tool_call_decision(
            "shell",
            {"command": "rm -rf build"},
            mode_def,
        )

        self.assertFalse(decision.allowed)
        self.assertEqual(decision.action, "ask")

    def test_action_shell_destructive_allows_after_approval(self):
        mode_def = ModeManager.get_instance().get_mode("action")
        decision = policy_engine.tool_call_decision(
            "shell",
            {"command": "rm -rf build", "policy_approved": True},
            mode_def,
        )

        self.assertTrue(decision.allowed)

    def test_explore_blocks_shell_write_patterns(self):
        self.assertFalse(shell_command_is_read_only("python -c \"open('x','w').write('y')\""))
        self.assertFalse(shell_command_is_read_only("git checkout main"))
        self.assertFalse(shell_command_is_read_only("echo x > file.txt"))

    def test_prompt_builder_filters_write_tools_in_explore(self):
        names = [
            t["function"]["name"]
            for t in PromptBuilder("x", get_default_tools(), mode="explore").build_tools()
        ]

        self.assertIn("read", names)
        self.assertIn("shell", names)
        self.assertNotIn("create", names)
        self.assertNotIn("edit", names)
        self.assertNotIn("call_mcp_tool", names)

    def test_base_agent_blocks_forged_tool_call(self):
        agent = BaseAgent(api_key="mock", model="mock", base_url="https://example.com")
        mode_def = ModeManager.get_instance().get_mode("explore")

        err = agent._tool_policy_error("write_file", {"path": "x.txt"}, mode_def)

        self.assertIsNotNone(err)
        self.assertIn("blocked by policy", err)

    def test_unknown_mcp_tool_hidden_until_capabilities_configured(self):
        mock_mgr = MagicMock()
        mock_mgr.get_active_tools.return_value = [
            {
                "type": "function",
                "function": {"name": "fs_read", "description": "", "parameters": {}},
                "_mcp_server": "fs",
                "_mcp_tool_name": "read",
            }
        ]
        mock_mgr.get_tool_capabilities.return_value = []

        with patch("core.mcp_manager.get_mcp_manager", return_value=mock_mgr):
            names = [
                t["function"]["name"]
                for t in PromptBuilder("x", [], mode="action").build_tools()
            ]

        self.assertNotIn("fs_read", names)

    def test_configured_mcp_read_tool_visible(self):
        mock_mgr = MagicMock()
        mock_mgr.get_active_tools.return_value = [
            {
                "type": "function",
                "function": {"name": "fs_read", "description": "", "parameters": {}},
                "_mcp_server": "fs",
                "_mcp_tool_name": "read",
            }
        ]
        mock_mgr.get_tool_capabilities.return_value = ["fs.read"]
        mock_mgr.get_capabilities_for_exposed_tool.return_value = ["fs.read"]

        with patch("core.mcp_manager.get_mcp_manager", return_value=mock_mgr):
            names = [
                t["function"]["name"]
                for t in PromptBuilder("x", [], mode="action").build_tools()
            ]

        self.assertIn("fs_read", names)


if __name__ == "__main__":
    unittest.main()
