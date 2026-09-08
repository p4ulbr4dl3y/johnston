"""Tests for Johnston CLI doctor command."""
from __future__ import annotations

import io
import subprocess
import sys
import unittest
import urllib.error
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from johnston_core.interfaces.cli.commands.doctor_cmd import (
    _ping_local_endpoint,
    diagnose_config_dirs,
    diagnose_git,
    diagnose_mcp,
    diagnose_providers,
    diagnose_python,
    diagnose_uv,
    format_checklist_item,
    run_doctor,
)
from johnston_core.interfaces.cli.entrypoint import main


class TestCLIDoctor(unittest.TestCase):
    def test_format_checklist_item_plain(self):
        self.assertEqual(format_checklist_item("✓", "ok", colorize=False), "  [✓] ok")
        self.assertEqual(format_checklist_item("✗", "err", colorize=False), "  [✗] err")
        self.assertEqual(format_checklist_item("!", "warn", colorize=False), "  [!] warn")

    def test_format_checklist_item_colored(self):
        with patch("johnston_core.interfaces.cli.commands.doctor_cmd.supports_color", return_value=True):
            ok_item = format_checklist_item("✓", "ok", colorize=True)
            self.assertIn("\033[32m[✓]\033[0m", ok_item)
            err_item = format_checklist_item("✗", "err", colorize=True)
            self.assertIn("\033[31m[✗]\033[0m", err_item)
            warn_item = format_checklist_item("!", "warn", colorize=True)
            self.assertIn("\033[33m[!]\033[0m", warn_item)

    def test_diagnose_python_supported(self):
        with patch.object(sys, "version_info", (3, 11, 2)):
            sym, msg = diagnose_python()
            self.assertEqual(sym, "✓")
            self.assertIn("v3.11.2", msg)

    def test_diagnose_python_unsupported(self):
        with patch.object(sys, "version_info", (3, 9, 7)):
            sym, msg = diagnose_python()
            self.assertEqual(sym, "!")
            self.assertIn("recommended", msg)

        with patch.object(sys, "version_info", (3, 14, 0)):
            sym, msg = diagnose_python()
            self.assertEqual(sym, "!")

    def test_diagnose_uv_missing(self):
        with patch("shutil.which", return_value=None):
            sym, msg = diagnose_uv()
            self.assertEqual(sym, "!")
            self.assertIn("not found in PATH", msg)

    def test_diagnose_uv_present_success(self):
        mock_proc = MagicMock(returncode=0, stdout="uv 0.4.18\n")
        with patch("shutil.which", return_value="/bin/uv"), patch("subprocess.run", return_value=mock_proc):
            sym, msg = diagnose_uv()
            self.assertEqual(sym, "✓")
            self.assertIn("uv 0.4.18", msg)

    def test_diagnose_uv_present_failure(self):
        with patch("shutil.which", return_value="/bin/uv"), patch("subprocess.run", side_effect=Exception("boom")):
            sym, msg = diagnose_uv()
            self.assertEqual(sym, "!")
            self.assertIn("version check failed", msg)

    def test_diagnose_config_dirs_writable(self):
        with patch("os.makedirs"), patch("os.access", return_value=True), patch("os.path.exists", return_value=True):
            results = diagnose_config_dirs(project_dir="/fake/proj")
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0][0], "✓")
            self.assertEqual(results[1][0], "✓")

    def test_diagnose_config_dirs_not_writable(self):
        with patch("os.makedirs"), patch("os.access", return_value=False), patch("os.path.exists", return_value=True):
            results = diagnose_config_dirs(project_dir="/fake/proj")
            self.assertEqual(len(results), 2)
            self.assertEqual(results[0][0], "✗")
            self.assertEqual(results[1][0], "✗")

    def test_diagnose_config_dirs_oserror(self):
        with patch("os.makedirs", side_effect=OSError("Disk read-only")):
            results = diagnose_config_dirs(project_dir="/fake/proj")
            self.assertEqual(results[0][0], "✗")
            self.assertIn("failed", results[0][1])

    def test_diagnose_git_missing(self):
        with patch("shutil.which", return_value=None):
            sym, msg = diagnose_git()
            self.assertEqual(sym, "!")
            self.assertIn("Git: not found in PATH", msg)

    def test_diagnose_git_not_a_repo(self):
        mock_proc = MagicMock(returncode=1)
        with patch("shutil.which", return_value="/bin/git"), patch("subprocess.run", return_value=mock_proc):
            sym, msg = diagnose_git()
            self.assertEqual(sym, "!")
            self.assertIn("not inside a git repository", msg)

    def test_diagnose_git_clean_working_tree(self):
        p_tree = MagicMock(returncode=0)
        p_branch = MagicMock(returncode=0, stdout="main\n")
        p_status = MagicMock(returncode=0, stdout="")

        def side_effect(cmd, **kwargs):
            if "rev-parse" in cmd:
                return p_tree
            if "branch" in cmd:
                return p_branch
            if "status" in cmd:
                return p_status
            return MagicMock(returncode=0)

        with patch("shutil.which", return_value="/bin/git"), patch("subprocess.run", side_effect=side_effect):
            sym, msg = diagnose_git()
            self.assertEqual(sym, "✓")
            self.assertIn("clean working tree", msg)
            self.assertIn("branch: main", msg)

    def test_diagnose_git_dirty_working_tree(self):
        p_tree = MagicMock(returncode=0)
        p_branch = MagicMock(returncode=0, stdout="feat/test\n")
        p_status = MagicMock(returncode=0, stdout=" M file1.py\n?? file2.py\n")

        def side_effect(cmd, **kwargs):
            if "rev-parse" in cmd:
                return p_tree
            if "branch" in cmd:
                return p_branch
            if "status" in cmd:
                return p_status
            return MagicMock(returncode=0)

        with patch("shutil.which", return_value="/bin/git"), patch("subprocess.run", side_effect=side_effect):
            sym, msg = diagnose_git()
            self.assertEqual(sym, "!")
            self.assertIn("dirty working tree", msg)
            self.assertIn("2 uncommitted file(s)", msg)

    def test_diagnose_git_exception(self):
        with patch("shutil.which", return_value="/bin/git"), patch("subprocess.run", side_effect=subprocess.SubprocessError("fail")):
            sym, msg = diagnose_git()
            self.assertEqual(sym, "!")
            self.assertIn("Git check failed", msg)

    def test_ping_local_endpoint(self):
        self.assertIsNone(_ping_local_endpoint("https://api.openai.com/v1"))

        with patch("urllib.request.urlopen") as mock_open:
            self.assertTrue(_ping_local_endpoint("http://localhost:11434"))

            mock_open.side_effect = urllib.error.HTTPError("http://127.0.0.1:1234", 404, "Not Found", {}, None)
            self.assertTrue(_ping_local_endpoint("http://127.0.0.1:1234"))

            mock_open.side_effect = ConnectionRefusedError("Connection refused")
            self.assertFalse(_ping_local_endpoint("http://127.0.0.1:1234"))

    def test_diagnose_providers_empty(self):
        pm = MagicMock()
        pm.load_providers.return_value = {}

        results = diagnose_providers(pm)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], "!")
        self.assertIn("No LLM providers configured", results[0][1])

    def test_diagnose_providers_active_ready_and_unset(self):
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pm.get_disabled_providers.return_value = ["custom-disabled"]
        pm.load_providers.return_value = {
            "openai": {"model": "gpt-4o", "api_key": "sk-12345", "enabled": True},
            "anthropic": {"model": "claude-3-5", "api_key": "", "enabled": True},
            "ollama": {"model": "llama3", "api_type": "ollama", "base_url": "http://localhost:11434", "enabled": True},
            "custom-disabled": {"model": "m1", "enabled": False},
        }
        pm.load_provider_def.return_value = None
        pm.get_api_key.side_effect = lambda k: "sk-12345" if k == "openai" else ""
        pm.get_provider_model.side_effect = lambda k: {"openai": "gpt-4o", "anthropic": "claude-3-5", "ollama": "llama3", "custom-disabled": "m1"}.get(k, "")

        with patch("johnston_core.interfaces.cli.commands.doctor_cmd._ping_local_endpoint", return_value=True):
            results = diagnose_providers(pm)

        self.assertEqual(results[0][0], "✓")
        self.assertIn("openai' (active): ready", results[0][1])

        self.assertEqual(results[1][0], "✗")
        self.assertIn("anthropic': API key unset", results[1][1])

        self.assertEqual(results[2][0], "✓")
        self.assertIn("ollama': ready", results[2][1])
        self.assertIn("server reachable", results[2][1])

        self.assertEqual(results[3][0], "!")
        self.assertIn("custom-disabled': disabled", results[3][1])

    def test_diagnose_providers_many_unconfigured_defaults(self):
        pm = MagicMock()
        pm.get_active_provider_key.return_value = "openai"
        pm.get_disabled_providers.return_value = []
        providers = {
            "openai": {"model": "gpt-4o", "api_key": "sk-test", "enabled": True},
        }
        # Add 10 unconfigured default providers
        for i in range(10):
            providers[f"def-{i}"] = {"model": "m", "api_key": "", "enabled": True}

        pm.load_providers.return_value = providers
        pm.load_provider_def.return_value = None
        pm.get_api_key.side_effect = lambda k: "sk-test" if k == "openai" else ""
        pm.get_provider_model.side_effect = lambda k: "gpt-4o" if k == "openai" else ""

        with patch("johnston_core.interfaces.cli.commands.doctor_cmd.DEFAULT_JSON_PROVIDERS", {f"def-{i}": {} for i in range(10)}):
            results = diagnose_providers(pm)

        self.assertEqual(results[0][0], "✓")
        self.assertIn("openai", results[0][1])
        self.assertEqual(results[1][0], "!")
        self.assertIn("10 other default provider(s) have no API key set", results[1][1])

    def test_diagnose_mcp_empty(self):
        mgr = MagicMock()
        mgr.load_servers.return_value = []

        results = diagnose_mcp(mgr)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], "!")
        self.assertIn("No MCP servers configured", results[0][1])

    def test_diagnose_mcp_servers(self):
        mgr = MagicMock()
        mgr.load_servers.return_value = [
            {"name": "srv-cmd-ok", "command": "uvx test-mcp", "enabled": True},
            {"name": "srv-cmd-missing", "command": "nonexistent-tool", "enabled": True},
            {"name": "srv-url-ok", "url": "https://mcp.example.com", "enabled": True},
            {"name": "srv-url-bad", "url": "ftp://bad-url", "enabled": True},
            {"name": "srv-empty", "enabled": True},
            {"name": "srv-disabled", "command": "cat", "enabled": False},
        ]
        mgr.get_active_tools.return_value = [
            {"_mcp_server": "srv-cmd-ok", "_mcp_tool_name": "tool1"},
            {"_mcp_server": "srv-cmd-ok", "_mcp_tool_name": "tool2"},
        ]

        def mock_which(cmd):
            return "/bin/" + cmd if cmd in ("uvx", "cat") else None

        with patch("shutil.which", side_effect=mock_which), patch("os.path.exists", return_value=False):
            results = diagnose_mcp(mgr)

        self.assertEqual(results[0][0], "✓")
        self.assertIn("srv-cmd-ok", results[0][1])
        self.assertIn("2 tool(s)", results[0][1])

        self.assertEqual(results[1][0], "✗")
        self.assertIn("srv-cmd-missing': command not found", results[1][1])

        self.assertEqual(results[2][0], "✓")
        self.assertIn("srv-url-ok': endpoint valid", results[2][1])

        self.assertEqual(results[3][0], "✗")
        self.assertIn("srv-url-bad': invalid URL", results[3][1])

        self.assertEqual(results[4][0], "✗")
        self.assertIn("srv-empty': missing command or URL", results[4][1])

        self.assertEqual(results[5][0], "!")
        self.assertIn("srv-disabled': disabled", results[5][1])

    def test_run_doctor_all_clean(self):
        pm = MagicMock()
        pm.load_providers.return_value = {"openai": {"enabled": True, "api_key": "sk-1"}}
        pm.get_active_provider_key.return_value = "openai"
        pm.get_disabled_providers.return_value = []
        pm.load_provider_def.return_value = None
        pm.get_api_key.return_value = "sk-1"

        mgr = MagicMock()
        mgr.load_servers.return_value = []

        with (
            patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_python", return_value=("✓", "Python OK")),
            patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_uv", return_value=("✓", "uv OK")),
            patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_config_dirs", return_value=[("✓", "Config OK")]),
            patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_git", return_value=("✓", "Git OK")),
            patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_providers", return_value=[("✓", "Provider OK")]),
            patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_mcp", return_value=[("✓", "MCP OK")]),
        ):
            out = io.StringIO()
            with redirect_stdout(out):
                code = run_doctor(pm=pm, mcp_mgr=mgr)

            self.assertEqual(code, 0)
            self.assertIn("All diagnostic checks passed successfully!", out.getvalue())

    def test_run_doctor_with_warnings(self):
        pm = MagicMock()
        mgr = MagicMock()

        with (
            patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_python", return_value=("✓", "Python OK")),
            patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_uv", return_value=("✓", "uv OK")),
            patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_config_dirs", return_value=[("✓", "Config OK")]),
            patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_git", return_value=("!", "Git warning")),
            patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_providers", return_value=[("✓", "Provider OK")]),
            patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_mcp", return_value=[("✓", "MCP OK")]),
        ):
            out = io.StringIO()
            with redirect_stdout(out):
                code = run_doctor(pm=pm, mcp_mgr=mgr)

            self.assertEqual(code, 0)
            self.assertIn("Doctor completed with warnings.", out.getvalue())

    def test_run_doctor_with_errors(self):
        pm = MagicMock()
        mgr = MagicMock()

        with (
            patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_python", return_value=("✓", "Python OK")),
            patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_uv", return_value=("✓", "uv OK")),
            patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_config_dirs", return_value=[("✗", "Config Not Writable")]),
            patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_git", return_value=("✓", "Git OK")),
            patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_providers", return_value=[("✓", "Provider OK")]),
            patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_mcp", return_value=[("✓", "MCP OK")]),
        ):
            out = io.StringIO()
            with redirect_stdout(out):
                code = run_doctor(pm=pm, mcp_mgr=mgr)

            self.assertEqual(code, 1)
            self.assertIn("Doctor found configuration issues that need attention.", out.getvalue())

    def test_cli_doctor_via_main(self):
        with patch("johnston_core.interfaces.cli.commands.doctor_cmd.run_doctor", return_value=0) as m_doc:
            with self.assertRaises(SystemExit) as cm:
                main(["doctor"])
            self.assertEqual(cm.exception.code, 0)
            self.assertEqual(m_doc.call_count, 1)


    def test_diagnose_mcp_command_list(self):
        mgr = MagicMock()
        mgr.load_servers.return_value = [
            {"name": "srv-list-ok", "command": ["npx", "-y", "@mcp/server"], "enabled": True},
            {"name": "srv-list-missing", "command": ["nonexistent-bin", "arg1"], "enabled": True},
        ]
        mgr.get_active_tools.return_value = []
        mgr.get_server_status.return_value = {"tools": 3}

        def mock_which(cmd):
            return "/usr/local/bin/npx" if cmd == "npx" else None

        with patch("shutil.which", side_effect=mock_which), patch("os.path.exists", return_value=False):
            results = diagnose_mcp(mgr)

        self.assertEqual(len(results), 2)
        self.assertEqual(results[0][0], "✓")
        self.assertIn("srv-list-ok", results[0][1])
        self.assertIn("npx -y @mcp/server", results[0][1])
        self.assertIn("3 tool(s)", results[0][1])

        self.assertEqual(results[1][0], "✗")
        self.assertIn("srv-list-missing", results[1][1])
        self.assertIn("command not found ('nonexistent-bin arg1')", results[1][1])


    def test_run_doctor_json_output(self):
        import json
        out = io.StringIO()
        args = MagicMock(json=True)
        with patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_python", return_value=("✓", "Python v3.11")), \
             patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_uv", return_value=("✓", "uv installed")), \
             patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_config_dirs", return_value=[("✓", "config ok")]), \
             patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_git", return_value=("✓", "git clean")), \
             patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_providers", return_value=[("✓", "openai ready")]), \
             patch("johnston_core.interfaces.cli.commands.doctor_cmd.diagnose_mcp", return_value=[("✓", "mcp ok")]):
            with redirect_stdout(out):
                code = run_doctor(args=args)

        self.assertEqual(code, 0)
        report = json.loads(out.getvalue())
        self.assertEqual(report["status"], "ok")
        self.assertIn("Environment", report["sections"])
        self.assertEqual(report["sections"]["Environment"][0]["status"], "ok")


if __name__ == "__main__":
    unittest.main()
