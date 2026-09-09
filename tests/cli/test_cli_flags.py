"""Tests for Johnston CLI startup and execution flags."""
from __future__ import annotations

import asyncio
import io
import logging
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from unittest.mock import AsyncMock, MagicMock, patch

from johnston.cli.commands.run_cmd import run_headless, run_headless_async
from johnston.cli.entrypoint import build_parser, main
from johnston.core.application.permission.permission_manager import PermissionManager
from johnston.core.domain.policies.permission_policy import ExecutionMode
from johnston.core.infrastructure.storage.session_store import SessionStore
from johnston.tui.app.app import JohnstonApp
from johnston.tui.presentation.widgets.chat_input import ChatInput


class TestCLIRootParserFlags(unittest.TestCase):
    """Test argument parsing for root parser flags."""

    def setUp(self):
        self.parser = build_parser()

    def test_continue_flag(self):
        args = self.parser.parse_args(["-c"])
        self.assertTrue(args.continue_latest)
        args2 = self.parser.parse_args(["--continue"])
        self.assertTrue(args2.continue_latest)

    def test_resume_flag(self):
        args = self.parser.parse_args(["--resume"])
        self.assertEqual(args.resume, "")
        args2 = self.parser.parse_args(["--resume", "sess_custom_123"])
        self.assertEqual(args2.resume, "sess_custom_123")
        args3 = self.parser.parse_args([])
        self.assertIsNone(args3.resume)

    def test_prompt_flag(self):
        args = self.parser.parse_args(["-p", "hello from prompt"])
        self.assertEqual(args.prompt, "hello from prompt")
        args2 = self.parser.parse_args(["--prompt", "hello long prompt"])
        self.assertEqual(args2.prompt, "hello long prompt")

    def test_model_flag(self):
        args = self.parser.parse_args(["-m", "gpt-4o"])
        self.assertEqual(args.model, "gpt-4o")
        args2 = self.parser.parse_args(["--model", "claude-3-5-sonnet"])
        self.assertEqual(args2.model, "claude-3-5-sonnet")

    def test_role_flag(self):
        args = self.parser.parse_args(["-r", "planner"])
        self.assertEqual(args.role, "planner")
        args2 = self.parser.parse_args(["--role", "reviewer"])
        self.assertEqual(args2.role, "reviewer")

    def test_branch_flag(self):
        args = self.parser.parse_args(["-b", "feat/test"])
        self.assertEqual(args.branch, "feat/test")
        args2 = self.parser.parse_args(["--branch", "feat/my-branch"])
        self.assertEqual(args2.branch, "feat/my-branch")

    def test_mode_flag(self):
        for mode in ("review", "edits", "yolo"):
            args = self.parser.parse_args(["--mode", mode])
            self.assertEqual(args.mode, mode)

    def test_mode_flag_invalid(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["--mode", "invalid_mode"])

    def test_effort_flag(self):
        for effort in ("low", "medium", "high"):
            args = self.parser.parse_args(["--effort", effort])
            self.assertEqual(args.effort, effort)

    def test_effort_flag_invalid(self):
        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["--effort", "ultra"])

    def test_sandbox_mutually_exclusive(self):
        args = self.parser.parse_args(["--sandbox"])
        self.assertTrue(args.sandbox)
        self.assertFalse(args.no_sandbox)

        args2 = self.parser.parse_args(["--no-sandbox"])
        self.assertFalse(args2.sandbox)
        self.assertTrue(args2.no_sandbox)

        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["--sandbox", "--no-sandbox"])

    def test_cwd_flag(self):
        args = self.parser.parse_args(["-C", "/tmp/project"])
        self.assertEqual(args.cwd, "/tmp/project")
        args2 = self.parser.parse_args(["--cwd", "/var/test"])
        self.assertEqual(args2.cwd, "/var/test")

    def test_theme_flag(self):
        args = self.parser.parse_args(["--theme", "dracula"])
        self.assertEqual(args.theme, "dracula")

    def test_debug_flag(self):
        args = self.parser.parse_args(["--debug"])
        self.assertTrue(args.debug)


class TestCLIRunSubparserFlags(unittest.TestCase):
    """Test argument parsing for run subparser flags."""

    def setUp(self):
        self.parser = build_parser()

    def test_run_continue_flag(self):
        args = self.parser.parse_args(["run", "-c", "my prompt"])
        self.assertEqual(args.subcommand, "run")
        self.assertTrue(args.continue_latest)
        self.assertEqual(args.prompt, "my prompt")

        args2 = self.parser.parse_args(["run", "--continue", "my prompt"])
        self.assertTrue(args2.continue_latest)

    def test_run_resume_flag(self):
        args = self.parser.parse_args(["run", "--resume", "sess_123", "do work"])
        self.assertEqual(args.resume, "sess_123")
        self.assertEqual(args.prompt, "do work")

        args2 = self.parser.parse_args(["run", "--resume"])
        self.assertEqual(args2.resume, "")
        self.assertIsNone(args2.prompt)

    def test_run_effort_flag(self):
        for effort in ("low", "medium", "high"):
            args = self.parser.parse_args(["run", "--effort", effort, "prompt"])
            self.assertEqual(args.effort, effort)

    def test_run_sandbox_flags(self):
        args = self.parser.parse_args(["run", "--sandbox", "test"])
        self.assertTrue(args.sandbox)
        self.assertFalse(args.no_sandbox)

        args2 = self.parser.parse_args(["run", "--no-sandbox", "test"])
        self.assertFalse(args2.sandbox)
        self.assertTrue(args2.no_sandbox)

        with redirect_stderr(io.StringIO()):
            with self.assertRaises(SystemExit):
                self.parser.parse_args(["run", "--sandbox", "--no-sandbox", "test"])

    def test_run_cwd_flag(self):
        args = self.parser.parse_args(["run", "-C", "/tmp", "test"])
        self.assertEqual(args.cwd, "/tmp")

        args2 = self.parser.parse_args(["run", "--cwd", "/var/tmp", "test"])
        self.assertEqual(args2.cwd, "/var/tmp")

    def test_run_debug_flag(self):
        args = self.parser.parse_args(["run", "--debug", "test"])
        self.assertTrue(args.debug)


class TestCLIDirectoryAndDebugExecution(unittest.TestCase):
    """Test handling of -C/--cwd and --debug in entrypoint and run_cmd."""

    def setUp(self):
        self.orig_cwd = os.getcwd()
        self.orig_log_level = logging.getLogger().level

    def tearDown(self):
        os.chdir(self.orig_cwd)
        logging.getLogger().setLevel(self.orig_log_level)

    def test_entrypoint_invalid_cwd_exits(self):
        err = io.StringIO()
        with redirect_stderr(err):
            with self.assertRaises(SystemExit) as cm:
                main(["-C", "/nonexistent/test/path/never/exists"])
        self.assertEqual(cm.exception.code, 1)
        self.assertIn("does not exist", err.getvalue())

    def test_entrypoint_valid_cwd_changes_dir(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            real_tmp = os.path.realpath(tmp_dir)
            with patch("johnston.tui.app.JohnstonApp.run"):
                with patch("johnston.tui.app.JohnstonApp.__init__", return_value=None):
                    with self.assertRaises(SystemExit) as cm:
                        main(["-C", tmp_dir])
                    self.assertEqual(cm.exception.code, 0)
                    self.assertEqual(os.path.realpath(os.getcwd()), real_tmp)

    def test_entrypoint_debug_sets_logging_level(self):
        with patch("johnston.tui.app.JohnstonApp.run"):
            with patch("johnston.tui.app.JohnstonApp.__init__", return_value=None):
                with self.assertRaises(SystemExit) as cm:
                    main(["--debug"])
                self.assertEqual(cm.exception.code, 0)
                self.assertEqual(logging.getLogger().level, logging.DEBUG)

    def test_run_headless_invalid_cwd_returns_1(self):
        err = io.StringIO()
        args = MagicMock(cwd="/nonexistent/path/for/test/xyz", debug=False, prompt="test")
        with redirect_stderr(err):
            code = run_headless(args)
        self.assertEqual(code, 1)
        self.assertIn("does not exist", err.getvalue())

    def test_run_headless_async_invalid_cwd_returns_1(self):
        async def run_test():
            err = io.StringIO()
            args = MagicMock(cwd="/nonexistent/async/path/abc", debug=False, prompt="test")
            with redirect_stderr(err):
                code = await run_headless_async(args)
            self.assertEqual(code, 1)
            self.assertIn("does not exist", err.getvalue())

        asyncio.run(run_test())

    def test_run_headless_debug_sets_logging(self):
        args = MagicMock(cwd=None, debug=True, prompt="test")
        with patch("johnston.cli.commands.run_cmd.run_headless_async", new_callable=AsyncMock) as mock_async:
            mock_async.return_value = 0
            code = run_headless(args)
            self.assertEqual(code, 0)
            self.assertEqual(logging.getLogger().level, logging.DEBUG)


class TestJohnstonAppStartupFlags(unittest.TestCase):
    """Test that JohnstonApp.__init__ applies all startup flags."""

    def test_app_init_with_theme(self):
        with patch.object(JohnstonApp, "__post_init__", lambda self: None, create=True):
            app = JohnstonApp(theme="nord")
            self.assertEqual(app.theme, "nord")

    def test_app_init_with_model(self):
        app = JohnstonApp(model="claude-3-5-sonnet")
        if app.agent:
            self.assertEqual(app.agent.model, "claude-3-5-sonnet")

    def test_app_init_with_effort(self):
        app = JohnstonApp(effort="high")
        if app.agent:
            self.assertEqual(app.agent.thinking_effort, "high")
            self.assertEqual(app.agent.reasoning_effort, "high")

    def test_app_init_with_sandbox(self):
        app = JohnstonApp(sandbox=True)
        self.assertTrue(app.sandbox_enabled)
        if app.agent:
            self.assertTrue(app.agent.sandbox_enabled)

        app_no_sb = JohnstonApp(sandbox=False)
        self.assertFalse(app_no_sb.sandbox_enabled)
        if app_no_sb.agent:
            self.assertFalse(app_no_sb.agent.sandbox_enabled)

    def test_app_init_with_mode(self):
        JohnstonApp(mode="yolo")
        self.assertEqual(PermissionManager.get_instance().execution_mode, ExecutionMode.YOLO)
        JohnstonApp(mode="review")
        self.assertEqual(PermissionManager.get_instance().execution_mode, ExecutionMode.REVIEW)

    def test_app_init_with_role(self):
        app = JohnstonApp(role="worker")
        self.assertEqual(app.role, "worker")
        if app.agent:
            self.assertEqual(app.agent.role, "worker")

    def test_app_init_initial_prompt(self):
        app = JohnstonApp(initial_prompt="write some code")
        self.assertEqual(app.initial_prompt, "write some code")

    def test_app_init_continue_latest(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            store = SessionStore.get_instance(project_path=tmp_dir)
            s1 = store.create_main("session-old")
            s1.messages = [{"role": "user", "text": "hello"}]
            store.save(s1)

            s2 = store.create_main("session-latest")
            s2.messages = [{"role": "user", "text": "latest msg"}]
            store.save(s2)

            with patch("johnston.core.infrastructure.storage.session_store.SessionStore.get_instance", return_value=store):
                with patch.object(SessionStore, "list_main_sessions", return_value=[{"id": "session-latest"}]):
                    app = JohnstonApp(continue_latest=True)
                    self.assertEqual(app.resume_session_id, "session-latest")

    def test_app_init_continue_latest_does_not_override_explicit_resume(self):
        with patch.object(SessionStore, "list_main_sessions", return_value=[{"id": "session-latest"}]):
            app = JohnstonApp(resume_session_id="session-explicit", continue_latest=True)
            self.assertEqual(app.resume_session_id, "session-explicit")


class TestRunCmdExecutionFlags(unittest.IsolatedAsyncioTestCase):
    """Test flag propagation in run_headless_async."""

    async def test_effort_and_sandbox_and_continue_propagation(self):
        mock_agent = MagicMock()
        mock_agent.stream_steps = MagicMock()

        async def fake_stream(_prompt):
            if False:
                yield None

        mock_agent.stream_steps.return_value = fake_stream("test")
        mock_agent.close = MagicMock()

        mock_pm = MagicMock()
        mock_pm.get_active_provider_key.return_value = "mock_provider"
        pdef = MagicMock()
        pdef.enabled = True
        pdef.key = "mock_provider"
        mock_pm.load_provider_def.return_value = pdef
        mock_pm.provider_needs_key.return_value = False
        mock_pm.create_agent_for_provider.return_value = mock_agent

        # Mock SessionStore
        mock_session = MagicMock()
        mock_session.agent_history = [{"role": "user", "content": "prior turn"}]
        mock_session.messages = [{"role": "user", "text": "prior turn"}]
        mock_session.tokens_input = 15
        mock_session.tokens_output = 25
        mock_session.total_tokens = 40
        mock_session.cost_usd = 0.002

        mock_store = MagicMock()
        mock_store.list_main_sessions.return_value = [{"id": "latest-sess-id"}]
        mock_store.get.return_value = mock_session

        args = MagicMock(
            prompt="my prompt",
            provider=None,
            model="custom-model",
            role="worker",
            effort="high",
            sandbox=True,
            no_sandbox=False,
            continue_latest=True,
            resume=None,
            cwd=None,
            debug=False,
            quiet=True,
            json=False,
        )

        with patch("johnston.core.infrastructure.storage.session_store.SessionStore.get_instance", return_value=mock_store):
            code = await run_headless_async(args, pm=mock_pm)

        self.assertEqual(code, 0)
        self.assertEqual(mock_agent.model, "custom-model")
        self.assertEqual(mock_agent.thinking_effort, "high")
        self.assertEqual(mock_agent.reasoning_effort, "high")
        self.assertTrue(mock_agent.sandbox_enabled)
        self.assertEqual(mock_agent.history, [{"role": "user", "content": "prior turn"}])
        self.assertEqual(mock_agent.tokens_input, 15)
        self.assertEqual(mock_agent.total_tokens, 40)

    async def test_no_sandbox_propagation(self):
        mock_agent = MagicMock()

        async def fake_stream(_prompt):
            if False:
                yield None

        mock_agent.stream_steps.return_value = fake_stream("test")
        mock_pm = MagicMock()
        mock_pm.get_active_provider_key.return_value = "mock_provider"
        pdef = MagicMock()
        pdef.enabled = True
        pdef.key = "mock_provider"
        mock_pm.load_provider_def.return_value = pdef
        mock_pm.provider_needs_key.return_value = False
        mock_pm.create_agent_for_provider.return_value = mock_agent

        args = MagicMock(
            prompt="prompt",
            provider=None,
            model=None,
            role="worker",
            effort=None,
            sandbox=False,
            no_sandbox=True,
            continue_latest=False,
            resume=None,
            cwd=None,
            debug=False,
            quiet=True,
            json=False,
        )
        code = await run_headless_async(args, pm=mock_pm)
        self.assertEqual(code, 0)
        self.assertFalse(mock_agent.sandbox_enabled)

    async def test_resume_specific_session_propagation(self):
        mock_agent = MagicMock()

        async def fake_stream(_prompt):
            if False:
                yield None

        mock_agent.stream_steps.return_value = fake_stream("test")
        mock_pm = MagicMock()
        mock_pm.get_active_provider_key.return_value = "mock_provider"
        pdef = MagicMock()
        pdef.enabled = True
        pdef.key = "mock_provider"
        mock_pm.load_provider_def.return_value = pdef
        mock_pm.provider_needs_key.return_value = False
        mock_pm.create_agent_for_provider.return_value = mock_agent

        mock_session = MagicMock()
        mock_session.agent_history = [{"role": "user", "content": "history from id"}]
        mock_session.messages = []
        mock_session.tokens_input = 5
        mock_session.tokens_output = 10
        mock_session.total_tokens = 15
        mock_session.cost_usd = 0.001

        mock_store = MagicMock()
        mock_store.get.return_value = mock_session

        args = MagicMock(
            prompt="prompt",
            provider=None,
            model=None,
            role="worker",
            effort=None,
            sandbox=False,
            no_sandbox=False,
            continue_latest=False,
            resume="specific-session-id",
            cwd=None,
            debug=False,
            quiet=True,
            json=False,
        )

        with patch("johnston.core.infrastructure.storage.session_store.SessionStore.get_instance", return_value=mock_store):
            code = await run_headless_async(args, pm=mock_pm)

        self.assertEqual(code, 0)
        mock_store.get.assert_called_with("specific-session-id")
        self.assertEqual(mock_agent.history, [{"role": "user", "content": "history from id"}])


class TestLifecycleInitialPrompt(unittest.IsolatedAsyncioTestCase):
    """Test initial prompt posting in LifecycleMixin."""

    async def test_on_mount_schedules_initial_prompt(self):
        from johnston.tui.mixins.lifecycle import LifecycleMixin

        class MockApp(LifecycleMixin):
            def __init__(self):
                self.initial_prompt = "Hello AI"
                self.resume_session_id = None
                self.current_session_id = "test-sess"
                self.is_app_active = False
                self.pm = MagicMock()
                self.created_tasks = []
                self._mock_input = MagicMock()

            def create_tracked_task(self, coro):
                self.created_tasks.append(coro)
                return asyncio.create_task(coro)

            def query_one(self, selector, _cls=None):
                if selector == "#message-input":
                    return self._mock_input
                return MagicMock()

            def refresh_status_footer(self):
                pass

        app = MockApp()
        mock_mcp = MagicMock()
        mock_mcp.ensure_tools_ready_async = AsyncMock()
        with patch("johnston.core.domain.policies.models_catalog.catalog.load_cache"):
            with patch("johnston.core.domain.policies.models_catalog.catalog.refresh", new_callable=AsyncMock):
                with patch("johnston.core.infrastructure.mcp.get_mcp_manager", return_value=mock_mcp):
                    app.on_mount()

        self.assertTrue(getattr(app, "_initial_prompt_posted", False))
        # Wait for the async task to run
        await asyncio.sleep(0.08)
        app._mock_input.add_to_history.assert_called_with("Hello AI")
        self.assertTrue(app._mock_input.post_message.called)
        submitted_event = app._mock_input.post_message.call_args[0][0]
        self.assertIsInstance(submitted_event, ChatInput.Submitted)
        self.assertEqual(submitted_event.value, "Hello AI")


class TestMainEntrypointFlagDispatch(unittest.TestCase):
    """Test entrypoint.main() passes all new flags to JohnstonApp."""

    @patch("johnston.tui.app.JohnstonApp.run")
    def test_main_passes_all_flags(self, mock_run):
        with patch("johnston.tui.app.JohnstonApp.__init__", return_value=None) as mock_app_init:
            with self.assertRaises(SystemExit) as cm:
                main([
                    "-c",
                    "--resume", "sess_999",
                    "-p", "Initial prompt text",
                    "-m", "gemini-2.5-flash",
                    "-r", "planner",
                    "--mode", "yolo",
                    "--effort", "high",
                    "--sandbox",
                    "--theme", "zinc-dark",
                ])
            self.assertEqual(cm.exception.code, 0)
            mock_app_init.assert_called_once_with(
                resume_session_id="sess_999",
                continue_latest=True,
                initial_prompt="Initial prompt text",
                model="gemini-2.5-flash",
                role="planner",
                mode="yolo",
                effort="high",
                sandbox=True,
                theme="zinc-dark",
            )

    @patch("johnston.tui.app.JohnstonApp.run")
    def test_main_branch_flag_switches_worktree(self, mock_run):
        with patch("johnston.tui.app.JohnstonApp.__init__", return_value=None), \
             patch("johnston.core.infrastructure.runtime.git_worktree.GitWorktreeManager.is_git_repo", return_value=True), \
             patch("johnston.core.infrastructure.runtime.git_worktree.GitWorktreeManager.get_repo_root", return_value="/fake/repo"), \
             patch("johnston.core.infrastructure.runtime.git_worktree.GitWorktreeManager.create_worktree", return_value=("/fake/wt", "feat/cool")), \
             patch("os.path.exists", return_value=True), \
             patch("os.chdir") as mock_chdir, \
             patch("johnston.tui.app.JohnstonApp.switch_project_dir") as mock_switch:
            with self.assertRaises(SystemExit) as cm:
                main(["-b", "feat/cool"])
            self.assertEqual(cm.exception.code, 0)
            mock_chdir.assert_called_with("/fake/wt")
            mock_switch.assert_called_once_with("/fake/wt", "feat/cool")

    def test_main_branch_flag_not_git_repo(self):
        with patch("johnston.core.infrastructure.runtime.git_worktree.GitWorktreeManager.is_git_repo", return_value=False), \
             patch("sys.stderr", new_callable=io.StringIO) as mock_err:
            with self.assertRaises(SystemExit) as cm:
                main(["-b", "feat/fail"])
            self.assertEqual(cm.exception.code, 1)
            self.assertIn("is not a git repository", mock_err.getvalue())
