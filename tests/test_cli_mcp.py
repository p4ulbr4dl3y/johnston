"""Tests for Johnston CLI mcp command."""
from __future__ import annotations

import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, patch

from core.infrastructure.mcp import config as mcp_config
from core.infrastructure.mcp.config import (
    add_server_config,
    remove_server_config,
    set_server_enabled,
)
from core.infrastructure.mcp.manager import MCPManager
from core.interfaces.cli.commands.mcp_cmd import (
    add_mcp,
    disable_mcp,
    enable_mcp,
    list_mcp,
    print_mcp,
    rm_mcp,
    run_mcp,
)
from core.interfaces.cli.entrypoint import build_parser, main


class TestCLIMCP(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.global_mcp = os.path.join(self.tmp_dir.name, "global_mcp.json")
        self.project_dir = os.path.join(self.tmp_dir.name, "myproject")
        os.makedirs(self.project_dir, exist_ok=True)
        self.patch_global = patch.object(mcp_config, "GLOBAL_MCP_FILE", self.global_mcp)
        self.patch_global.start()

    def tearDown(self):
        self.patch_global.stop()
        self.tmp_dir.cleanup()

    def test_list_mcp_table_output(self):
        f = io.StringIO()
        mgr = MagicMock()
        mgr.load_servers.return_value = [
            {
                "name": "srv1",
                "scope": "global",
                "command": "node",
                "args": ["s1.js", "--port", "3000"],
                "enabled": True,
            },
            {
                "name": "srv2",
                "scope": "project",
                "url": "https://example.com/sse",
                "enabled": False,
            },
        ]
        mgr.get_active_tools.return_value = [
            {"_mcp_server": "srv1", "_mcp_tool_name": "tool_a"},
            {"_mcp_server": "srv1", "_mcp_tool_name": "tool_b"},
        ]
        mgr.get_server_status.return_value = {"tools": 0}

        with redirect_stdout(f):
            code = list_mcp(mgr)

        self.assertEqual(code, 0)
        out = f.getvalue()
        self.assertIn("Server", out)
        self.assertIn("Scope", out)
        self.assertIn("Status", out)
        self.assertIn("Tools count", out)
        self.assertIn("Command/URL", out)
        # Server 1
        self.assertIn("srv1", out)
        self.assertIn("global", out)
        self.assertIn("enabled", out)
        self.assertIn("2", out)
        self.assertIn("node s1.js --port 3000", out)
        # Server 2
        self.assertIn("srv2", out)
        self.assertIn("project", out)
        self.assertIn("disabled", out)
        self.assertIn("https://example.com/sse", out)

    def test_list_mcp_no_cmd_no_url(self):
        f = io.StringIO()
        mgr = MagicMock()
        mgr.load_servers.return_value = [
            {"name": "empty_srv", "scope": "global", "enabled": True}
        ]
        mgr.get_active_tools.return_value = []
        mgr.get_server_status.return_value = {"tools": 0}

        with redirect_stdout(f):
            code = list_mcp(mgr)

        self.assertEqual(code, 0)
        self.assertIn("(none)", f.getvalue())

    def test_add_mcp_cmd(self):
        mgr = MagicMock()
        f = io.StringIO()
        with redirect_stdout(f):
            code = add_mcp(
                "my_server",
                cmd="python",
                args=["server.py", "--flag"],
                scope="project",
                mgr=mgr,
            )
        self.assertEqual(code, 0)
        mgr.add_server.assert_called_once_with(
            "my_server", cmd="python", url=None, args=["server.py", "--flag"], scope="project"
        )
        self.assertIn("MCP server 'my_server' added (project).", f.getvalue())

    def test_add_mcp_url(self):
        mgr = MagicMock()
        f = io.StringIO()
        with redirect_stdout(f):
            code = add_mcp(
                "sse_server",
                url="https://mcp.service.io/events",
                scope="global",
                mgr=mgr,
            )
        self.assertEqual(code, 0)
        mgr.add_server.assert_called_once_with(
            "sse_server", cmd=None, url="https://mcp.service.io/events", args=None, scope="global"
        )
        self.assertIn("MCP server 'sse_server' added (global).", f.getvalue())

    def test_add_mcp_validation(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = add_mcp("", cmd="node")
        self.assertEqual(code, 1)

        err2 = io.StringIO()
        with redirect_stderr(err2):
            code2 = add_mcp("name")
        self.assertEqual(code2, 1)

    def test_rm_mcp_success(self):
        mgr = MagicMock()
        mgr.remove_server.return_value = True
        f = io.StringIO()
        with redirect_stdout(f):
            code = rm_mcp("target_server", scope="global", mgr=mgr)
        self.assertEqual(code, 0)
        mgr.remove_server.assert_called_once_with("target_server", scope="global")
        self.assertIn("MCP server 'target_server' removed.", f.getvalue())

    def test_rm_mcp_not_found(self):
        mgr = MagicMock()
        mgr.remove_server.return_value = False
        err = io.StringIO()
        with redirect_stderr(err):
            code = rm_mcp("nonexistent", mgr=mgr)
        self.assertEqual(code, 1)
        self.assertIn("MCP server 'nonexistent' not found.", err.getvalue())

    def test_rm_mcp_validation(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = rm_mcp("")
        self.assertEqual(code, 1)

    def test_enable_mcp_success(self):
        mgr = MagicMock()
        mgr.set_server_enabled.return_value = True
        f = io.StringIO()
        with redirect_stdout(f):
            code = enable_mcp("srv1", scope="project", mgr=mgr)
        self.assertEqual(code, 0)
        mgr.set_server_enabled.assert_called_once_with("srv1", True, scope="project")
        self.assertIn("MCP server 'srv1' enabled.", f.getvalue())

    def test_enable_mcp_not_found(self):
        mgr = MagicMock()
        mgr.set_server_enabled.return_value = False
        err = io.StringIO()
        with redirect_stderr(err):
            code = enable_mcp("unknown", mgr=mgr)
        self.assertEqual(code, 1)
        self.assertIn("MCP server 'unknown' not found.", err.getvalue())

    def test_enable_mcp_validation(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = enable_mcp("")
        self.assertEqual(code, 1)

    def test_disable_mcp_success(self):
        mgr = MagicMock()
        mgr.set_server_enabled.return_value = True
        f = io.StringIO()
        with redirect_stdout(f):
            code = disable_mcp("srv1", scope="global", mgr=mgr)
        self.assertEqual(code, 0)
        mgr.set_server_enabled.assert_called_once_with("srv1", False, scope="global")
        self.assertIn("MCP server 'srv1' disabled.", f.getvalue())

    def test_disable_mcp_not_found(self):
        mgr = MagicMock()
        mgr.set_server_enabled.return_value = False
        err = io.StringIO()
        with redirect_stderr(err):
            code = disable_mcp("unknown", mgr=mgr)
        self.assertEqual(code, 1)
        self.assertIn("MCP server 'unknown' not found.", err.getvalue())

    def test_disable_mcp_validation(self):
        err = io.StringIO()
        with redirect_stderr(err):
            code = disable_mcp("")
        self.assertEqual(code, 1)

    def test_run_mcp_routing(self):
        mgr = MagicMock()
        parser = build_parser()

        # default list
        args = parser.parse_args(["mcp"])
        code = run_mcp(args, mgr)
        self.assertEqual(code, 0)

        # explicit list
        args = parser.parse_args(["mcp", "list"])
        code = run_mcp(args, mgr)
        self.assertEqual(code, 0)

        # add with cmd and args
        args = parser.parse_args(["mcp", "add", "s1", "--cmd", "node", "--args", "a.js", "b.js", "--scope", "project"])
        code = run_mcp(args, mgr)
        self.assertEqual(code, 0)
        mgr.add_server.assert_called_with("s1", cmd="node", url=None, args=["a.js", "b.js"], scope="project")

        # add with url
        args = parser.parse_args(["mcp", "add", "s2", "--url", "https://api.test/mcp"])
        code = run_mcp(args, mgr)
        self.assertEqual(code, 0)
        mgr.add_server.assert_called_with("s2", cmd=None, url="https://api.test/mcp", args=None, scope="global")

        # rm
        mgr.remove_server.return_value = True
        args = parser.parse_args(["mcp", "rm", "s1", "--scope", "project"])
        code = run_mcp(args, mgr)
        self.assertEqual(code, 0)
        mgr.remove_server.assert_called_with("s1", scope="project")

        # enable
        mgr.set_server_enabled.return_value = True
        args = parser.parse_args(["mcp", "enable", "s1"])
        code = run_mcp(args, mgr)
        self.assertEqual(code, 0)
        mgr.set_server_enabled.assert_called_with("s1", True, scope=None)

        # disable
        mgr.set_server_enabled.return_value = True
        args = parser.parse_args(["mcp", "disable", "s1", "--scope", "global"])
        code = run_mcp(args, mgr)
        self.assertEqual(code, 0)
        mgr.set_server_enabled.assert_called_with("s1", False, scope="global")

    def test_run_mcp_unknown_action(self):
        args = MagicMock()
        args.mcp_action = "unknown_action"
        err = io.StringIO()
        with redirect_stderr(err):
            code = run_mcp(args)
        self.assertEqual(code, 1)

    def test_main_subcommand_mcp(self):
        with patch("core.interfaces.cli.commands.mcp_cmd.run_mcp", return_value=0) as mock_run:
            with self.assertRaises(SystemExit) as cm:
                main(["mcp", "list"])
            self.assertEqual(cm.exception.code, 0)
            mock_run.assert_called_once()

    def test_mcp_config_file_lifecycle_integration(self):
        # Global config operations
        add_server_config("g_srv", cmd="npx", args=["-y", "pkg"], scope="global", global_file=self.global_mcp)
        with open(self.global_mcp, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIn("g_srv", data["mcpServers"])
        self.assertEqual(data["mcpServers"]["g_srv"]["command"], "npx")

        # Disable
        set_server_enabled("g_srv", False, scope="global", global_file=self.global_mcp)
        with open(self.global_mcp, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertFalse(data["mcpServers"]["g_srv"]["enabled"])

        # Enable
        set_server_enabled("g_srv", True, scope="global", global_file=self.global_mcp)
        with open(self.global_mcp, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertTrue(data["mcpServers"]["g_srv"]["enabled"])

        # Project config operations
        add_server_config("p_srv", url="https://proj.mcp", scope="project", project_dir=self.project_dir)
        proj_file = os.path.join(self.project_dir, ".johnston", "mcp.json")
        self.assertTrue(os.path.exists(proj_file))
        with open(proj_file, "r", encoding="utf-8") as f:
            p_data = json.load(f)
        self.assertIn("p_srv", p_data["mcpServers"])
        self.assertEqual(p_data["mcpServers"]["p_srv"]["url"], "https://proj.mcp")

        # Remove from project
        removed = remove_server_config("p_srv", scope="project", project_dir=self.project_dir)
        self.assertTrue(removed)
        with open(proj_file, "r", encoding="utf-8") as f:
            p_data = json.load(f)
        self.assertNotIn("p_srv", p_data["mcpServers"])

        # Remove from global
        removed_g = remove_server_config("g_srv", scope="global", global_file=self.global_mcp)
        self.assertTrue(removed_g)
        with open(self.global_mcp, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertNotIn("g_srv", data["mcpServers"])

    def test_mcp_manager_facade_integration(self):
        mgr = MCPManager(project_dir=self.project_dir)
        mgr.global_file = self.global_mcp
        mgr.add_server("facade_srv", cmd="echo", scope="global")
        servers = mgr.load_servers()
        target = next((s for s in servers if s["name"] == "facade_srv"), None)
        self.assertIsNotNone(target)
        self.assertEqual(target["command"], "echo")

        # Disable via manager
        mgr.set_server_enabled("facade_srv", False, scope="global")
        servers = mgr.load_servers()
        target = next((s for s in servers if s["name"] == "facade_srv"), None)
        self.assertFalse(target.get("enabled", True))

        # Remove via manager
        res = mgr.remove_server("facade_srv", scope="global")
        self.assertTrue(res)
        servers = mgr.load_servers()
        target = next((s for s in servers if s["name"] == "facade_srv"), None)
        self.assertIsNone(target)

    def test_print_mcp_legacy(self):
        f = io.StringIO()
        with redirect_stdout(f):
            print_mcp()
        self.assertIn("Configured MCP Servers:", f.getvalue())


    def test_add_mcp_splits_command(self):
        mgr = MagicMock()
        code = add_mcp("my-server", cmd="npx -y @mcp/server", mgr=mgr)
        self.assertEqual(code, 0)
        mgr.add_server.assert_called_once_with(
            "my-server",
            cmd="npx",
            url=None,
            args=["-y", "@mcp/server"],
            scope="global",
        )

    def test_add_server_config_splits_command(self):
        add_server_config(
            "split_srv",
            cmd="npx -y @mcp/server",
            scope="global",
            global_file=self.global_mcp,
        )
        with open(self.global_mcp, "r", encoding="utf-8") as f:
            data = json.load(f)
        entry = data["mcpServers"]["split_srv"]
        self.assertEqual(entry["command"], "npx")
        self.assertEqual(entry["args"], ["-y", "@mcp/server"])


if __name__ == "__main__":
    unittest.main()
