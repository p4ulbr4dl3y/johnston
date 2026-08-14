import unittest
from unittest.mock import MagicMock, patch

from textual.app import App, ComposeResult

from core.tasks.manager import TaskManager
from widgets.status_footer import StatusFooter


class DummyTask:
    def __init__(
        self,
        task_id: str,
        is_running: bool = True,
        is_background: bool = True,
        session_id: str = "test-session",
        kind: str = "shell",
    ):
        self.id = task_id
        self.task_id = task_id
        self.kind = kind
        self.is_running = is_running
        self.is_background = is_background
        self.session_id = session_id


class StubPM:
    """Provider manager stub without get_provider_thinking_effort."""

    def get_active_provider_key(self):
        return "openai"

    def load_providers(self):
        return {"openai": {"name": "OpenAI"}}

    def is_provider_connected(self, key, info=None):
        return True


class FooterTestApp(App):
    def __init__(self):
        super().__init__()
        self.current_session_id = "test-session"
        self.pm = MagicMock()
        self.pm.get_active_provider_key.return_value = "openai"
        self.pm.get_provider_thinking_effort.return_value = "high"

        self.agent = MagicMock()
        self.agent.model = "gpt-4o"
        self.agent.role = "action"
        self.agent.get_metrics.return_value = {
            "context_used": 15000,
            "total_tokens": 50000,
            "context": "128k",
            "context_limit": 128000,
            "cost_usd": 0.05,
        }

        class DummySession:
            def __init__(self, status: str):
                self.status = status

        self.sm = MagicMock()
        self.sm.get_subagents_for_parent.return_value = [
            DummySession("running"),
            DummySession("completed"),
        ]

        self.task_manager = TaskManager()
        self.task_manager.register(DummyTask("bash-1", is_running=True))

    def compose(self) -> ComposeResult:
        yield StatusFooter(id="status-footer")


class TestStatusFooter(unittest.IsolatedAsyncioTestCase):
    async def test_status_footer_rendering_and_subagents(self):
        app = FooterTestApp()
        async with app.run_test() as pilot:
            footer = app.query_one(StatusFooter)
            self.assertIsNotNone(footer)

            # Mount triggers refresh_footer
            footer.refresh_footer()
            await pilot.pause(0.1)

            # Verify last status args
            args = footer._last_status_args
            self.assertEqual(args["provider_key"], "openai")
            self.assertEqual(args["model_name"], "gpt-4o")
            self.assertEqual(args["active_bg_tasks"], 1)
            self.assertEqual(args["subagents_active"], 1)
            self.assertEqual(args["subagents_total"], 2)
            self.assertEqual(args["thinking_effort"], "high")
            self.assertIn("skills_visible", args)
            self.assertIn("skills_total", args)

            # Test generating spinner toggle
            footer.set_generating(True)
            self.assertTrue(footer.is_generating)
            self.assertIsNotNone(footer._spinner_timer)

            footer.set_generating(False)
            self.assertFalse(footer.is_generating)
            self.assertIsNone(footer._spinner_timer)

            # Test compact mode rendering
            footer.update_status(
                provider_key="openai",
                model_name="gpt-4o",
                active_bg_tasks=2,
                subagents_active=1,
                subagents_total=2,
            )

    def test_spin_without_last_status_args(self):
        footer = StatusFooter()
        with patch.object(footer, "refresh_footer") as mock_rf:
            footer._spin()
            mock_rf.assert_called_once()

    async def test_set_generating_noop_when_state_unchanged(self):
        app = FooterTestApp()
        async with app.run_test():
            footer = app.query_one(StatusFooter)
            footer.set_generating(True)
            self.assertTrue(footer.is_generating)
            footer.set_generating(True)  # no-op
            footer.set_generating(False)
            self.assertFalse(footer.is_generating)
            footer.set_generating(False)  # no-op

    async def test_refresh_footer_exception_falls_back_to_default(self):
        app = FooterTestApp()
        async with app.run_test():
            footer = app.query_one(StatusFooter)
            with patch("core.infrastructure.mcp.get_mcp_manager", side_effect=Exception("boom")):
                with patch.object(footer, "update_status") as mock_us:
                    footer.refresh_footer()
                    mock_us.assert_called_once_with(provider_key="default")

    async def test_refresh_footer_clean_model_placeholder(self):
        app = FooterTestApp()
        async with app.run_test() as pilot:
            footer = app.query_one(StatusFooter)
            with patch("core.models_catalog.catalog.get_model_display_name", return_value=""):
                footer.refresh_footer()
                await pilot.pause()
            self.assertEqual(footer._last_status_args["clean_model"], "[Select model: /models]")

    async def test_refresh_footer_thinking_effort_fallback(self):
        app = FooterTestApp()
        app.pm = StubPM()
        app.agent.thinking_effort = "medium"
        async with app.run_test() as pilot:
            footer = app.query_one(StatusFooter)
            await pilot.pause()
            self.assertEqual(footer._last_status_args["thinking_effort"], "medium")

    async def test_refresh_footer_mcp_active_counting(self):
        app = FooterTestApp()
        async with app.run_test() as pilot:
            footer = app.query_one(StatusFooter)
            mgr = MagicMock()
            mgr.load_servers.return_value = [
                {"name": "url-only", "url": "http://x", "command": None, "disabled": False},
                {"name": "err-client", "command": "python", "disabled": False},
                {"name": "good", "command": "python", "disabled": False},
                {"name": "off", "command": "python", "disabled": True},
            ]
            mgr.clients = {
                "err-client": MagicMock(last_error="boom"),
                "good": MagicMock(last_error=None),
            }
            footer._mcp_cache_time = 0  # force reload of cached servers
            with patch("core.infrastructure.mcp.get_mcp_manager", return_value=mgr):
                footer.refresh_footer()
                await pilot.pause()
            self.assertEqual(footer._last_status_args["mcp_active"], 1)
            self.assertEqual(footer._last_status_args["mcp_total"], 3)

    async def test_update_status_fallback_branches(self):
        app = FooterTestApp()
        async with app.run_test():
            footer = app.query_one(StatusFooter)
            with patch("core.models_catalog.catalog.get_model_display_name", return_value=""):
                footer.update_status(provider_key="openai", model_name="gpt-4o", is_connected=True)
            footer.update_status(provider_key="openai", is_connected=True, model_name="")
            footer.update_status(provider_key="openai", is_connected=False, model_name="")

    async def test_update_status_compact_mode(self):
        app = FooterTestApp()
        async with app.run_test(size=(60, 24)):
            footer = app.query_one(StatusFooter)
            with patch.object(app, "query_one", return_value=MagicMock(clipboard_attachments=[1, 2])):
                footer.update_status(
                    provider_key="openai",
                    provider_display="OpenAI",
                    is_connected=True,
                    model_name="gpt-4o",
                    active_bg_tasks=1,
                    subagents_active=1,
                    subagents_total=2,
                    context_used=1000,
                    context_limit=128000,
                    total_tokens=5000,
                    mcp_active=1,
                    mcp_total=2,
                )
            footer.update_status(provider_key="openai", provider_display="OpenAI", is_connected=True, model_name="")
            footer.update_status(provider_key="openai", provider_display="OpenAI", is_connected=False, model_name="")

    async def test_update_status_noncompact_attachments(self):
        app = FooterTestApp()
        async with app.run_test():
            footer = app.query_one(StatusFooter)
            with patch.object(app, "query_one", return_value=MagicMock(clipboard_attachments=[1, 2])):
                footer.update_status(
                    provider_key="openai", provider_display="OpenAI", is_connected=True, model_name="gpt-4o"
                )
            with patch.object(app, "query_one", return_value=MagicMock(clipboard_attachments=[1])):
                footer.update_status(
                    provider_key="openai", provider_display="OpenAI", is_connected=True, model_name="gpt-4o"
                )

    async def test_mcp_footer_text_loading_counter(self):
        footer = StatusFooter()
        # Partial load -> active/total counter
        self.assertEqual(footer._mcp_footer_text(0, 2), "MCP: [#f4f4f5]0/2[/#f4f4f5]")
        self.assertEqual(footer._mcp_footer_text(1, 2), "MCP: [#f4f4f5]1/2[/#f4f4f5]")
        # Fully loaded -> plain count
        self.assertEqual(footer._mcp_footer_text(2, 2), "MCP: [#f4f4f5]2/2[/#f4f4f5]")
        # No servers configured -> 0/0
        self.assertEqual(footer._mcp_footer_text(0, 0), "MCP: [#f4f4f5]0/0[/#f4f4f5]")

    async def test_poll_mcp_refresh_triggers_on_loading(self):
        footer = StatusFooter()
        mgr = MagicMock()
        mgr.is_loading.return_value = True
        with patch("core.infrastructure.mcp.get_mcp_manager", return_value=mgr):
            with patch.object(footer, "refresh_footer") as mock_rf:
                footer._poll_mcp_refresh()
                mock_rf.assert_called_once()
                self.assertTrue(getattr(footer, "_mcp_was_loading", False))

                mgr.is_loading.return_value = False
                mock_rf.reset_mock()
                footer._poll_mcp_refresh()
                mock_rf.assert_called_once()  # final cleanup call
                self.assertFalse(getattr(footer, "_mcp_was_loading", False))

                mock_rf.reset_mock()
                footer._poll_mcp_refresh()
                mock_rf.assert_called_once()  # first idle detects count change (None -> 0)
                self.assertEqual(footer._mcp_last_active, 0)

                mock_rf.reset_mock()
                footer._poll_mcp_refresh()
                mock_rf.assert_not_called()  # idle, count unchanged

    async def test_subagent_footer_mount_unmount_and_spin(self):
        from widgets.status_footer import SubagentStatusFooter

        class SubagentFooterApp(App[None]):
            def compose(self):
                yield SubagentStatusFooter(id="subagent-status-footer")

        app = SubagentFooterApp()
        async with app.run_test():
            footer = app.query_one(SubagentStatusFooter)

            sess = MagicMock()
            sess.agent = None
            sess.role = "explorer"
            sess.status = "running"
            sess.project_dir = "/tmp/test"
            sess.branch_name = "feat"
            sess.last_context_tokens = 500
            sess.total_tokens = 1200
            sess.cost_usd = 0.05

            footer.update_session(sess)
            self.assertTrue(footer.is_generating)
            self.assertIsNotNone(footer._spinner_timer)

            # Test _spin re-renders with next frame
            old_idx = footer._spinner_idx
            footer._spin()
            self.assertEqual(footer._spinner_idx, old_idx + 1)

            # Test on_unmount cleans up timers
            footer.on_unmount()
            self.assertIsNone(footer._spinner_timer)

    async def test_subagent_footer_old_session_fallback_metrics(self):
        from widgets.status_footer import SubagentStatusFooter

        class SubagentFooterApp(App[None]):
            def compose(self):
                yield SubagentStatusFooter(id="subagent-status-footer")

        app = SubagentFooterApp()
        async with app.run_test():
            footer = app.query_one(SubagentStatusFooter)

            sess = MagicMock()
            sess.agent = None
            sess.role = "explorer"
            sess.status = "completed"
            sess.project_dir = "/tmp/test"
            sess.branch_name = "main"
            sess.last_context_tokens = 0
            sess.total_tokens = 0
            sess.cost_usd = 0.0
            sess.messages = [{"role": "user", "content": "hello " * 50}]

            footer.update_session(sess)
            self.assertFalse(footer.is_generating)
            self.assertIsNone(footer._spinner_timer)

    def test_format_display_path(self):
        import os

        from widgets.status_footer import format_display_path

        home = os.path.realpath(os.path.expanduser("~"))
        # Home dir itself
        self.assertEqual(format_display_path(home), "~")
        # Subdir in home
        self.assertEqual(format_display_path(os.path.join(home, "johnston")), "~/johnston")
        # Deep worktree in home
        self.assertEqual(
            format_display_path(os.path.join(home, ".johnston", "worktrees", "subagent-123")),
            "~/.johnston/worktrees/subagent-123",
        )
        # Outside home
        self.assertEqual(format_display_path("/tmp/myproject"), "/tmp/myproject")
        # Empty
        self.assertEqual(format_display_path(""), "")
        # Long path middle truncation
        very_long = os.path.join(home, "a", "b", "c", "d", "e", "f", "g", "long_subagent_folder_name_xyz")
        res = format_display_path(very_long, max_length=30)
        self.assertIn("...", res)
        self.assertTrue(res.startswith("~/"))


