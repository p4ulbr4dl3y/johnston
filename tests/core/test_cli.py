import io
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import MagicMock, mock_open, patch

from app import (
    get_version,
    print_mcp,
    print_models,
    print_modes,
    print_rules,
    print_skills,
    print_subagents,
)
from cli import print_linters, run_headless_prompt


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
                    with patch("tomllib.load", return_value={"project": {"version": "9.9.9"}}):
                        self.assertEqual(get_version(), "9.9.9")

    def test_get_version_pyproject_error_returns_dev(self):
        from importlib.metadata import PackageNotFoundError

        with patch("cli.version", side_effect=PackageNotFoundError("no pkg")):
            with patch("pathlib.Path.exists", return_value=True):
                with patch("tomllib.load", side_effect=Exception("bad tom")):
                    self.assertEqual(get_version(), "0.1.0-dev")

    def test_print_mcp_tools_scan_exception(self):
        f = io.StringIO()
        with patch("core.mcp_manager.get_mcp_manager") as mock_get:
            mgr = MagicMock()
            mgr.load_servers.return_value = [
                {"name": "srv", "command": "x", "scope": "global", "mode": "eager"}
            ]
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
                with patch("core.rules_manager.RulesManager") as mock_cls:
                    rules_mgr = MagicMock()
                    rules_mgr.load_rules.return_value = []
                    mock_cls.get_instance.return_value = rules_mgr
                    with redirect_stdout(f):
                        print_rules()
        out = f.getvalue()
        self.assertIn("AGENTS.md [project instruction]", out)
        self.assertIn("bytes)", out)

    def test_print_rules_with_modes_and_globs(self):
        import pathlib
        import tempfile

        f = io.StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            with patch("pathlib.Path.cwd", return_value=pathlib.Path(tmp)):
                with patch("core.rules_manager.RulesManager") as mock_cls:
                    rule = MagicMock()
                    rule.name = "R1"
                    rule.source = "project"
                    rule.modes = ["act", "explore"]
                    rule.globs = ["*.py"]
                    rules_mgr = MagicMock()
                    rules_mgr.load_rules.return_value = [rule]
                    mock_cls.get_instance.return_value = rules_mgr
                    with redirect_stdout(f):
                        print_rules()
        out = f.getvalue()
        self.assertIn("R1 [rule] [project]", out)
        self.assertIn("Modes: act, explore", out)
        self.assertIn("Globs: *.py", out)

    def test_print_linters_empty(self):
        f = io.StringIO()
        with patch("core.linters_manager.get_linters_manager") as mock_get:
            mgr = MagicMock()
            mgr.load_linters.return_value = []
            mgr.scan_available.return_value = {}
            mock_get.return_value = mgr
            with redirect_stdout(f):
                print_linters()
        self.assertIn("No linters configured", f.getvalue())

    def test_print_linters_with_items(self):
        f = io.StringIO()
        with patch("core.linters_manager.get_linters_manager") as mock_get:
            mgr = MagicMock()
            mgr.load_linters.return_value = [
                {
                    "name": "ruff",
                    "label": "Ruff",
                    "scope": "project",
                    "enabled": True,
                    "extensions": ["py"],
                    "cmd": ["ruff", "check"],
                },
                {"name": "eslint", "scope": "preset", "enabled": False, "extensions": [], "cmd": []},
            ]
            mgr.scan_available.return_value = {"ruff": True, "eslint": False}
            mock_get.return_value = mgr
            with redirect_stdout(f):
                print_linters()
        out = f.getvalue()
        self.assertIn("Ruff [project] [enabled] [available]", out)
        self.assertIn("py", out)
        self.assertIn("ruff check", out)
        self.assertIn("eslint [preset] [disabled] [unavailable]", out)
        self.assertIn("(none)", out)

    def test_print_models_no_key_no_models_skipped(self):
        f = io.StringIO()
        pm = MagicMock()
        pm.load_providers.return_value = {"empty": {"name": "Empty"}}
        pm.get_active_provider_key.return_value = "empty"
        pm.get_api_key.return_value = ""
        with patch("cli.ProviderManager", return_value=pm):
            with redirect_stdout(f):
                from app import print_models
                print_models()
        self.assertIn("Available Johnston Providers & Models:", f.getvalue())

    def test_print_models_with_details(self):
        f = io.StringIO()
        pm = MagicMock()
        pm.load_providers.return_value = {
            "openai": {"name": "OpenAI", "model": "gpt-4o", "models": ["m1", "m2", "m3", "m4", "m5", "m6"], "base_url": "http://x"},
        }
        pm.get_active_provider_key.return_value = "openai"
        pm.get_api_key.return_value = "sk-123"
        with patch("cli.ProviderManager", return_value=pm):
            with redirect_stdout(f):
                from app import print_models
                print_models()
        out = f.getvalue()
        self.assertIn("* [openai] OpenAI [key set]", out)
        self.assertIn("Active Model: gpt-4o", out)
        self.assertIn("m1, m2, m3, m4, m5", out)
        self.assertIn("Base URL: http://x", out)

    def test_print_skills_empty(self):
        f = io.StringIO()
        with patch("core.skill_manager.SkillManager") as mock_cls:
            mock_cls.return_value.list_skills.return_value = []
            with redirect_stdout(f):
                print_skills()
        self.assertIn("No skills found", f.getvalue())

    def test_print_skills_with_path(self):
        f = io.StringIO()
        with patch("core.skill_manager.SkillManager") as mock_cls:
            mock_cls.return_value.list_skills.return_value = [
                {"name": "a", "scope": "global", "hidden": True, "path": "/tmp/a.md"},
                {"name": "b", "scope": "project"},
            ]
            with redirect_stdout(f):
                print_skills()
        out = f.getvalue()
        self.assertIn("a [global] [hidden]", out)
        self.assertIn("Path: /tmp/a.md", out)
        self.assertIn("b [project]", out)

    def test_print_mcp_empty(self):
        f = io.StringIO()
        with patch("core.mcp_manager.get_mcp_manager") as mock_get:
            mock_get.return_value.load_servers.return_value = []
            with redirect_stdout(f):
                print_mcp()
        self.assertIn("No MCP servers configured", f.getvalue())

    def test_print_mcp_cmd_with_args_disabled(self):
        f = io.StringIO()
        with patch("core.mcp_manager.get_mcp_manager") as mock_get:
            mgr = MagicMock()
            mgr.load_servers.return_value = [
                {"name": "srv", "command": "node", "args": ["a", "b"], "scope": "project", "mode": "eager", "disabled": True}
            ]
            mgr.get_active_tools.return_value = []
            mock_get.return_value = mgr
            with redirect_stdout(f):
                print_mcp()
        out = f.getvalue()
        self.assertIn("srv [project] [eager] [disabled]", out)
        self.assertIn("Command: node a b", out)

    def test_print_mcp_no_cmd_no_url(self):
        f = io.StringIO()
        with patch("core.mcp_manager.get_mcp_manager") as mock_get:
            mgr = MagicMock()
            mgr.load_servers.return_value = [
                {"name": "srv", "scope": "global", "mode": "eager"}
            ]
            mgr.get_active_tools.return_value = []
            mgr.clients = {}
            mock_get.return_value = mgr
            with redirect_stdout(f):
                print_mcp()
        out = f.getvalue()
        self.assertIn("Command: (none)", out)

    def test_print_mcp_client_error(self):
        f = io.StringIO()
        with patch("core.mcp_manager.get_mcp_manager") as mock_get:
            mgr = MagicMock()
            mgr.load_servers.return_value = [
                {"name": "srv", "command": "x", "scope": "global", "mode": "eager"}
            ]
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
        with patch("core.mcp_manager.get_mcp_manager") as mock_get:
            mgr = MagicMock()
            mgr.load_servers.return_value = [
                {"name": "srv", "command": "x", "scope": "global", "mode": "eager"}
            ]
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
                with patch("core.rules_manager.RulesManager") as mock_cls:
                    rules_mgr = MagicMock()
                    rules_mgr.load_rules.return_value = []
                    mock_cls.get_instance.return_value = rules_mgr
                    with redirect_stdout(f):
                        print_rules()
        self.assertIn("No rules or project instruction files", f.getvalue())


    def test_print_modes_with_disallowed_tools(self):
        f = io.StringIO()
        with patch("core.mode_manager.ModeManager") as mock_cls:
            mode_mgr = MagicMock()
            mode = MagicMock(
                read_only=False, source="builtin", disallowed_tools=["rm"],
            )
            type(mode).name = "Act"
            type(mode).key = "act"
            mode_mgr.load_modes.return_value = {"act": mode}
            mock_cls.get_instance.return_value = mode_mgr
            with redirect_stdout(f):
                print_modes()
        out = f.getvalue()
        self.assertIn("Act (act)", out)
        self.assertIn("Disallowed tools: rm", out)

    def test_print_subagents_empty(self):
        f = io.StringIO()
        with patch("core.subagent_registry.SubagentRegistry") as mock_cls:
            reg = MagicMock()
            reg.list_definitions.return_value = {}
            mock_cls.get_instance.return_value = reg
            with redirect_stdout(f):
                print_subagents()
        self.assertIn("No subagent definitions found", f.getvalue())

    def test_print_subagents_with_defs(self):
        f = io.StringIO()
        with patch("core.subagent_registry.SubagentRegistry") as mock_cls:
            reg = MagicMock()
            dval = MagicMock()
            dval.tools = ["shell"]
            dval.model = "gpt-4o"
            dval.source = "builtin"
            reg.list_definitions.return_value = {"worker": dval}
            mock_cls.get_instance.return_value = reg
            with redirect_stdout(f):
                print_subagents()
        out = f.getvalue()
        self.assertIn("worker", out)
        self.assertIn("Tools: shell", out)
        self.assertIn("Model: gpt-4o", out)


class TestHeadlessPrompt(unittest.TestCase):
    def test_run_headless_prompt_streams(self):
        f = io.StringIO()

        async def fake_stream(prompt):
            yield ("bot_delta", "Hello", "")
            yield ("bot_text", "Hello world", "")
            yield ("thinking_start", "Thinking...", "")
            yield ("thinking_end", "1.5", "")

        agent = MagicMock()
        agent.stream_steps = fake_stream

        pm = MagicMock()
        pm.create_active_agent.return_value = agent
        with patch("cli.ProviderManager", return_value=pm):
            with redirect_stdout(f):
                run_headless_prompt("hi")
        self.assertIn("Hello world", f.getvalue())

    def test_run_headless_prompt_no_agent_exits(self):
        pm = MagicMock()
        pm.create_active_agent.return_value = None
        with patch("cli.ProviderManager", return_value=pm):
            with self.assertRaises(SystemExit) as cm:
                with redirect_stderr(io.StringIO()):
                    run_headless_prompt("hi")
        self.assertEqual(cm.exception.code, 1)

    def test_run_headless_prompt_verbose_thinking(self):
        f_err = io.StringIO()

        async def fake_stream(prompt):
            yield ("thinking_delta", "some thinking here", "")
            yield ("tool", "bash", "run")
            yield ("tool_result", "output text", "")
            yield ("thinking_end", "2.0", "")

        agent = MagicMock()
        agent.stream_steps = fake_stream
        pm = MagicMock()
        pm.create_active_agent.return_value = agent
        with patch("cli.ProviderManager", return_value=pm):
            with redirect_stderr(f_err):
                run_headless_prompt("hi", verbose=True)
        self.assertIn("Thinking", f_err.getvalue())
        self.assertIn("Executing Tool", f_err.getvalue())
        self.assertIn("Tool Result", f_err.getvalue())

    def test_run_headless_prompt_non_verbose_thinking_end(self):
        f_err = io.StringIO()

        async def fake_stream(prompt):
            yield ("thinking_end", "2.0", "")

        agent = MagicMock()
        agent.stream_steps = fake_stream
        pm = MagicMock()
        pm.create_active_agent.return_value = agent
        with patch("cli.ProviderManager", return_value=pm):
            with redirect_stderr(f_err):
                run_headless_prompt("hi")
        self.assertEqual(f_err.getvalue(), "\x1b[K\r")

    def test_run_headless_prompt_shrinking_text_resets_len(self):
        f = io.StringIO()

        async def fake_stream(prompt):
            yield ("bot_text", "long text here", "")
            yield ("bot_text", "short", "")

        agent = MagicMock()
        agent.stream_steps = fake_stream
        pm = MagicMock()
        pm.create_active_agent.return_value = agent
        with patch("cli.ProviderManager", return_value=pm):
            with redirect_stdout(f):
                run_headless_prompt("hi")
        self.assertIn("short", f.getvalue())

    def test_run_headless_prompt_mcp_stop_exception(self):
        f = io.StringIO()

        async def fake_stream(prompt):
            yield ("bot_text", "done", "")

        agent = MagicMock()
        agent.stream_steps = fake_stream
        pm = MagicMock()
        pm.create_active_agent.return_value = agent
        with patch("cli.ProviderManager", return_value=pm):
            with patch("core.mcp_manager.get_mcp_manager") as mock_get:
                mock_get.return_value.stop_all.side_effect = Exception("boom")
                with redirect_stdout(f):
                    run_headless_prompt("hi")
        self.assertIn("done", f.getvalue())


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

    def test_main_modes_flag(self):
        with patch("sys.argv", ["johnston", "--modes"]):
            with patch("cli.print_modes"):
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

    def test_main_linters_flag(self):
        with patch("sys.argv", ["johnston", "--linters"]):
            with patch("cli.print_linters"):
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
                mock_app.sm.load_session.return_value = {"ui_messages": [{"type": "user", "text": "hi"}]}
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
                mock_app.sm.load_session.side_effect = Exception("boom")
                with self.assertRaises(SystemExit) as cm:
                    from cli import main
                    main()
        self.assertEqual(cm.exception.code, 0)


if __name__ == "__main__":
    unittest.main()


