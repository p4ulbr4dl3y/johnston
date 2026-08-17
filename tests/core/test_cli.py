import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, mock_open, patch

from cli import (
    get_version,
    print_mcp,
    print_models,
    print_roles,
    print_rules,
    print_skills,
    print_subagents,
)
from core.application.skills.manager import Skill, SkillScope


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

    @patch("core.infrastructure.mcp.MCPManager.load_servers")
    def test_print_mcp_url_error(self, mock_load):
        mock_load.return_value = [
            {"name": "hf_server", "url": "https://hf.co/mcp", "scope": "global", "disabled": False}
        ]
        f = io.StringIO()
        with redirect_stdout(f):
            print_mcp()
        output = f.getvalue()
        self.assertIn("hf_server", output)
        self.assertIn("URL: https://hf.co/mcp", output)
        self.assertIn("HTTP/SSE URL transport not supported yet", output)

    @patch("core.infrastructure.mcp.MCPManager.load_servers")
    @patch("core.infrastructure.mcp.MCPManager.get_active_tools")
    def test_print_mcp_with_tools(self, mock_tools, mock_load):
        mock_load.return_value = [
            {"name": "my_server", "command": "node server.js", "scope": "project", "disabled": False}
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

    def test_print_roles(self):
        f = io.StringIO()
        with redirect_stdout(f):
            print_roles()
        output = f.getvalue()
        self.assertIn("Available Agent Roles & Modes:", output)

    def test_print_subagents(self):
        f = io.StringIO()
        with redirect_stdout(f):
            print_subagents()
        output = f.getvalue()
        self.assertIn("Available Subagent Roles:", output)

    @patch("sys.argv", ["johnston", "-v"])
    def test_main_version(self):
        with self.assertRaises(SystemExit) as cm:
            from cli import main

            main()
        self.assertEqual(cm.exception.code, 0)

    @patch("sys.argv", ["johnston", "--resume", "sess123"])
    @patch("app.JohnstonApp.run")
    def test_main_app_start(self, mock_app_run):
        with self.assertRaises(SystemExit) as cm:
            from cli import main

            main()
        self.assertEqual(cm.exception.code, 0)
        self.assertTrue(mock_app_run.called)


class TestCLIAdvanced(unittest.TestCase):
    def test_get_version_fallback_to_pyproject(self):
        from importlib.metadata import PackageNotFoundError

        with patch("cli.version", side_effect=PackageNotFoundError("no pkg")):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("builtins.open", mock_open(read_data='{"project": {"version": "9.9.9"}}')):
                    with patch("cli.tomllib.load", return_value={"project": {"version": "9.9.9"}}):
                        self.assertEqual(get_version(), "9.9.9")

    def test_get_version_pyproject_error_returns_dev(self):
        from importlib.metadata import PackageNotFoundError

        with patch("cli.version", side_effect=PackageNotFoundError("no pkg")):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("cli.tomllib.load", side_effect=Exception("bad tom")):
                    self.assertEqual(get_version(), "0.1.0-dev")

    def test_print_mcp_tools_scan_exception(self):
        f = io.StringIO()
        with patch("core.infrastructure.mcp.get_mcp_manager") as mock_get:
            mgr = MagicMock()
            mgr.load_servers.return_value = [{"name": "srv", "command": "x", "scope": "global"}]
            mgr.get_active_tools.side_effect = Exception("boom")
            mgr.clients = {}
            mock_get.return_value = mgr
            with redirect_stdout(f):
                print_mcp()
        self.assertIn("srv", f.getvalue())

    def test_print_rules_with_file(self):
        import pathlib
        import tempfile

        f = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / "AGENTS.md").write_text("hello")
            with patch("pathlib.Path.cwd", return_value=pathlib.Path(tmp)):
                with patch("core.application.rules.rules.RulesManager") as mock_cls:
                    rules_mgr = MagicMock()
                    rules_mgr.load_rules.return_value = []
                    mock_cls.get_instance.return_value = rules_mgr
                    with redirect_stdout(f):
                        print_rules()
        out = f.getvalue()
        self.assertIn("AGENTS.md [project instruction]", out)
        self.assertIn("bytes)", out)

    def test_print_rules_with_roles(self):
        import pathlib
        import tempfile

        f = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("pathlib.Path.cwd", return_value=pathlib.Path(tmp)):
                with patch("core.application.rules.rules.RulesManager") as mock_cls:
                    rule = MagicMock()
                    rule.name = "R1"
                    rule.source = "project"
                    rule.roles = ["worker", "explorer"]
                    rules_mgr = MagicMock()
                    rules_mgr.load_rules.return_value = [rule]
                    mock_cls.get_instance.return_value = rules_mgr
                    with redirect_stdout(f):
                        print_rules()
        out = f.getvalue()
        self.assertIn("R1 [rule] [project]", out)
        self.assertIn("Roles: worker, explorer", out)

    def test_print_models_no_key_no_models_skipped(self):
        f = io.StringIO()
        pm = MagicMock()
        pm.load_providers.return_value = {"empty": {"name": "Empty"}}
        pm.get_active_provider_key.return_value = "empty"
        pm.get_api_key.return_value = ""
        with patch("cli.ProviderManager", return_value=pm):
            with redirect_stdout(f):
                from cli import print_models

                print_models()
        self.assertIn("Available Johnston Providers & Models:", f.getvalue())

    def test_print_models_with_details(self):
        f = io.StringIO()
        pm = MagicMock()
        pm.load_providers.return_value = {
            "openai": {
                "name": "OpenAI",
                "model": "gpt-4o",
                "models": ["m1", "m2", "m3", "m4", "m5", "m6"],
                "base_url": "http://x",
            },
        }
        pm.get_active_provider_key.return_value = "openai"
        pm.get_api_key.return_value = "sk-123"
        with patch("cli.ProviderManager", return_value=pm):
            with redirect_stdout(f):
                from cli import print_models

                print_models()
        out = f.getvalue()
        self.assertIn("* [openai] OpenAI [key set]", out)
        self.assertIn("Active Model: gpt-4o", out)
        self.assertIn("m1, m2, m3, m4, m5", out)
        self.assertIn("Base URL: http://x", out)

    def test_print_skills_empty(self):
        f = io.StringIO()
        with patch("core.application.skills.manager.SkillManager") as mock_cls:
            mock_cls.return_value.list_skills.return_value = []
            with redirect_stdout(f):
                print_skills()
        self.assertIn("No skills found", f.getvalue())

    def test_print_skills_with_hidden(self):
        f = io.StringIO()
        with patch("core.application.skills.manager.SkillManager") as mock_cls:
            mock_cls.return_value.list_skills.return_value = [
                Skill("a", "", "", "", SkillScope.GLOBAL, True),
                Skill("b", "", "", "", SkillScope.PROJECT, False),
            ]
            with redirect_stdout(f):
                print_skills()
        out = f.getvalue()
        self.assertIn("a [global] [hidden]", out)
        self.assertIn("b [project]", out)

    def test_print_mcp_empty(self):
        f = io.StringIO()
        with patch("core.infrastructure.mcp.get_mcp_manager") as mock_get:
            mock_get.return_value.load_servers.return_value = []
            with redirect_stdout(f):
                print_mcp()
        self.assertIn("No MCP servers configured", f.getvalue())

    def test_print_mcp_cmd_with_args_disabled(self):
        f = io.StringIO()
        with patch("core.infrastructure.mcp.get_mcp_manager") as mock_get:
            mgr = MagicMock()
            mgr.load_servers.return_value = [
                {
                    "name": "srv",
                    "command": "node",
                    "args": ["a", "b"],
                    "scope": "project",
                    "disabled": True,
                }
            ]
            mgr.get_active_tools.return_value = []
            mock_get.return_value = mgr
            with redirect_stdout(f):
                print_mcp()
        out = f.getvalue()
        self.assertIn("srv [project] [disabled]", out)
        self.assertIn("Command: node a b", out)

    def test_print_mcp_no_cmd_no_url(self):
        f = io.StringIO()
        with patch("core.infrastructure.mcp.get_mcp_manager") as mock_get:
            mgr = MagicMock()
            mgr.load_servers.return_value = [{"name": "srv", "scope": "global"}]
            mgr.get_active_tools.return_value = []
            mgr.clients = {}
            mock_get.return_value = mgr
            with redirect_stdout(f):
                print_mcp()
        out = f.getvalue()
        self.assertIn("Command: (none)", out)

    def test_print_mcp_client_error(self):
        f = io.StringIO()
        with patch("core.infrastructure.mcp.get_mcp_manager") as mock_get:
            mgr = MagicMock()
            mgr.load_servers.return_value = [{"name": "srv", "command": "x", "scope": "global"}]
            mgr.get_active_tools.return_value = []
            client = MagicMock()
            client.last_error = "process failed"
            mgr.clients = {"srv": client}
            mock_get.return_value = mgr
            with redirect_stdout(f):
                print_mcp()
        self.assertIn("process failed", f.getvalue())

    def test_print_mcp_no_tools_no_client(self):
        f = io.StringIO()
        with patch("core.infrastructure.mcp.get_mcp_manager") as mock_get:
            mgr = MagicMock()
            mgr.load_servers.return_value = [{"name": "srv", "command": "x", "scope": "global"}]
            mgr.get_active_tools.return_value = []
            mgr.clients = {}
            mock_get.return_value = mgr
            with redirect_stdout(f):
                print_mcp()
        self.assertIn("No tools reported or server failed to respond", f.getvalue())

    def test_print_rules_no_items(self):
        import tempfile

        f = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("pathlib.Path.cwd", return_value=__import__("pathlib").Path(tmp)):
                with patch("core.application.rules.rules.RulesManager") as mock_cls:
                    rules_mgr = MagicMock()
                    rules_mgr.load_rules.return_value = []
                    mock_cls.get_instance.return_value = rules_mgr
                    with redirect_stdout(f):
                        print_rules()
        self.assertIn("No rules or project instruction files", f.getvalue())

    def test_print_roles_with_disallowed_tools(self):
        f = io.StringIO()
        with patch("core.role_registry.RoleRegistry") as mock_cls:
            role_mgr = MagicMock()
            role = MagicMock(
                source="builtin",
                disallowed_tools=["rm"],
                description="Worker mode",
                allowed_tools=[],
                scope="any",
            )
            type(role).name = "Worker"
            type(role).key = "worker"
            role_mgr.load_roles.return_value = {"worker": role}
            mock_cls.get_instance.return_value = role_mgr
            with redirect_stdout(f):
                print_roles()
        out = f.getvalue()
        self.assertIn("Worker (worker)", out)
        self.assertIn("Disallowed tools: rm", out)

    def test_print_subagents_empty(self):
        f = io.StringIO()
        with patch("core.role_registry.RoleRegistry") as mock_cls:
            reg = MagicMock()
            reg.list_subagent_roles.return_value = {}
            mock_cls.get_instance.return_value = reg
            with redirect_stdout(f):
                print_subagents()
        self.assertIn("No subagent roles found", f.getvalue())

    def test_print_subagents_with_defs(self):
        f = io.StringIO()
        with patch("core.role_registry.RoleRegistry") as mock_cls:
            reg = MagicMock()
            dval = MagicMock()
            dval.allowed_tools = ["shell"]
            dval.model = "gpt-4o"
            dval.source = "builtin"
            reg.list_subagent_roles.return_value = {"worker": dval}
            mock_cls.get_instance.return_value = reg
            with redirect_stdout(f):
                print_subagents()
        out = f.getvalue()
        self.assertIn("worker", out)
        self.assertIn("Tools: shell", out)
        self.assertIn("Model: gpt-4o", out)


class TestMainFlags(unittest.TestCase):
    def test_main_models_flag(self):
        with patch("sys.argv", ["johnston", "--models"]):
            with patch("cli.print_models"):
                with self.assertRaises(SystemExit) as cm:
                    from cli import main

                    main()
        self.assertEqual(cm.exception.code, 0)

    def test_main_skills_flag(self):
        with patch("sys.argv", ["johnston", "--skills"]):
            with patch("cli.print_skills"):
                with self.assertRaises(SystemExit) as cm:
                    from cli import main

                    main()
        self.assertEqual(cm.exception.code, 0)

    def test_main_mcp_flag(self):
        with patch("sys.argv", ["johnston", "--mcp"]):
            with patch("cli.print_mcp"):
                with self.assertRaises(SystemExit) as cm:
                    from cli import main

                    main()
        self.assertEqual(cm.exception.code, 0)

    def test_main_roles_flag(self):
        with patch("sys.argv", ["johnston", "--roles"]):
            with patch("cli.print_roles"):
                with self.assertRaises(SystemExit) as cm:
                    from cli import main

                    main()
        self.assertEqual(cm.exception.code, 0)

    def test_main_rules_flag(self):
        with patch("sys.argv", ["johnston", "--rules"]):
            with patch("cli.print_rules"):
                with self.assertRaises(SystemExit) as cm:
                    from cli import main

                    main()
        self.assertEqual(cm.exception.code, 0)

    def test_main_subagents_flag(self):
        with patch("sys.argv", ["johnston", "--subagents"]):
            with patch("cli.print_subagents"):
                with self.assertRaises(SystemExit) as cm:
                    from cli import main

                    main()
        self.assertEqual(cm.exception.code, 0)

    def test_main_app_keyboard_interrupt(self):
        with patch("sys.argv", ["johnston"]):
            with patch("app.JohnstonApp") as mock_app_cls:
                mock_app = mock_app_cls.return_value
                mock_app.run = MagicMock(side_effect=KeyboardInterrupt())
                mock_app.current_session_id = None
                with self.assertRaises(SystemExit) as cm:
                    from cli import main

                    main()
        self.assertEqual(cm.exception.code, 0)

    def test_main_resume_tip_printed(self):
        f = io.StringIO()
        with patch("sys.argv", ["johnston"]):
            with patch("app.JohnstonApp") as mock_app_cls:
                mock_app = mock_app_cls.return_value
                mock_app.run = MagicMock()
                mock_app.current_session_id = "sess123"
                mock_app.sm = MagicMock()
                mock_app.sm.get.return_value = MagicMock(messages=[{"type": "user", "text": "hi"}], agent_history=[])
                with redirect_stdout(f):
                    with self.assertRaises(SystemExit) as cm:
                        from cli import main

                        main()
        self.assertEqual(cm.exception.code, 0)
        self.assertIn("johnston --resume sess123", f.getvalue())

    def test_main_resume_tip_load_error(self):
        with patch("sys.argv", ["johnston"]):
            with patch("app.JohnstonApp") as mock_app_cls:
                mock_app = mock_app_cls.return_value
                mock_app.run = MagicMock()
                mock_app.current_session_id = "sess123"
                mock_app.sm = MagicMock()
                mock_app.sm.get.side_effect = Exception("boom")
                with self.assertRaises(SystemExit) as cm:
                    from cli import main

                    main()
        self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()
