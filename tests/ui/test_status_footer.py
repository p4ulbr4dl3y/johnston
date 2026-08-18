import asyncio
import sys
import unittest
from unittest.mock import MagicMock, patch

import pytest
from textual.app import App, ComposeResult

from core.infrastructure.tasks.manager import TaskManager
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
        self.sm.children.return_value = [
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
            self.assertEqual(args["attachments_count"], 0)
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
            mgr.active_server_count.return_value = 1
            footer._mcp_cache_time = 0  # force reload of cached servers
            # Force a fresh background cache load with the mocked manager.
            footer._st_cache_time = 0
            footer._st_cached_mcp_servers = None
            footer._st_cache_loading = False
            footer._st_cached_providers = {}
            with patch("core.infrastructure.mcp.get_mcp_manager", return_value=mgr):
                footer.refresh_footer()
                await pilot.pause()
                # Cache loads happen off the event loop; wait until the fresh
                # values are in place and the footer has re-rendered.
                for _ in range(50):
                    if footer._st_cached_mcp_servers:
                        break
                    await asyncio.sleep(0.01)
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
        # No servers configured -> 0
        self.assertEqual(footer._mcp_footer_text(0, 0), "MCP: [#f4f4f5]0[/#f4f4f5]")

    async def test_poll_mcp_refresh_triggers_on_loading(self):
        footer = StatusFooter()
        mgr = MagicMock()
        mgr.is_loading.return_value = True
        mgr.active_server_count.return_value = 0
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

            # Test _spin re-renders with next frame and cached rows without calling git diff
            old_idx = footer._spinner_idx
            with patch.object(footer, "_git_diff_stats") as diff_mock:
                footer._spin()
                diff_mock.assert_not_called()
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

    @pytest.mark.skipif(sys.platform == "win32", reason="expects POSIX-style separators")
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

    def test_render_stream_frame_normal_and_compact(self):
        footer = StatusFooter()
        footer.is_generating = True
        footer._spinner_idx = 1

        # Test normal 2-column rows
        footer._last_grid_rows = [("[bold #5eead4]Action[/]", "Right"), ("Ctx", "Tokens")]
        with patch.object(footer, "update") as mock_update:
            footer._render_stream_frame()
            mock_update.assert_called_once()

        # Test compact 1-column rows
        footer._last_grid_rows = [("[bold #5eead4]Action[/]",), ("Row2",)]
        with patch.object(footer, "update") as mock_update:
            footer._render_stream_frame()
            mock_update.assert_called_once()

    async def test_git_branch_preserves_last_known_on_async_refresh(self):
        footer = StatusFooter()
        footer._branch_text = "main"
        footer._branch_cwd = "/some/dir"
        footer._branch_time = 0.0

        # When get_git_info returns empty during async refresh
        with patch("core.application.generation.prompt_builder.get_git_info", return_value=""):
            branch = footer._git_branch(cwd="/some/dir")
            self.assertEqual(branch, "main")

    def test_git_diff_stats_with_cwd_and_fallback(self):
        footer = StatusFooter()
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="5\t2\tfile.py\n")
            res = footer._compute_diff_sync(cwd="/custom/path")
            self.assertEqual(res, "+5 / -2")
            mock_run.assert_called_with(
                ["git", "diff", "HEAD", "--numstat"],
                capture_output=True,
                text=True,
                timeout=2,
                cwd="/custom/path",
            )

    async def test_update_status_background_label(self):
        app = FooterTestApp()
        async with app.run_test():
            footer = app.query_one(StatusFooter)
            footer.update_status(
                provider_key="openai",
                model_name="gpt-4o",
                subagents_active=1,
                active_bg_tasks=2,
            )
            rows = footer._last_grid_rows
            row3_right = rows[2][1]
            self.assertIn("Background:", row3_right)
            self.assertIn("1 agent", row3_right)
            self.assertIn("2 shell", row3_right)

    async def test_update_status_background_label_empty(self):
        app = FooterTestApp()
        async with app.run_test():
            footer = app.query_one(StatusFooter)
            footer.update_status(provider_key="openai", model_name="gpt-4o")
            rows = footer._last_grid_rows
            self.assertEqual(rows[2][1], "")

    async def test_update_status_attachments_indicator(self):
        app = FooterTestApp()
        async with app.run_test():
            footer = app.query_one(StatusFooter)
            # 1 image attached
            footer.update_status(provider_key="openai", model_name="gpt-4o", attachments_count=1)
            row1_left = footer._last_grid_rows[0][0]
            self.assertIn("1 image attached", row1_left)

            # 2 images attached
            footer.update_status(provider_key="openai", model_name="gpt-4o", attachments_count=2)
            row1_left = footer._last_grid_rows[0][0]
            self.assertIn("2 images attached", row1_left)

            # 0 attachments
            footer.update_status(provider_key="openai", model_name="gpt-4o", attachments_count=0)
            row1_left = footer._last_grid_rows[0][0]
            self.assertNotIn("attached", row1_left)

    async def test_update_status_compact_attachments_indicator(self):
        app = FooterTestApp()
        async with app.run_test(size=(60, 24)):
            footer = app.query_one(StatusFooter)
            footer.update_status(provider_key="openai", model_name="gpt-4o", attachments_count=1)
            row1 = footer._last_grid_rows[0][0]
            self.assertIn("1 image attached", row1)



