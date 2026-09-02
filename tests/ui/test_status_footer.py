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
            self.assertFalse(getattr(footer, "ALLOW_SELECT", True))
            self.assertFalse(footer.allow_select)

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
            with patch("widgets.app.status_state.build_status_kwargs", side_effect=Exception("boom")):
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
        mgr = MagicMock()
        mgr.load_servers.return_value = [
            {"name": "url-only", "url": "http://x", "command": None},
            {"name": "err-client", "command": "python"},
            {"name": "good", "command": "python"},
            {"name": "off", "command": "python", "enabled": False},
        ]
        mgr.clients = {
            "err-client": MagicMock(last_error="boom"),
            "good": MagicMock(last_error=None),
        }
        mgr.active_server_count.return_value = 1
        from widgets.app.status_state import refresh_footer_cache

        with patch("core.infrastructure.mcp.get_mcp_manager", return_value=mgr):
            app = FooterTestApp()
            async with app.run_test() as pilot:
                footer = app.query_one(StatusFooter)
                await refresh_footer_cache(app, footer)
                footer.refresh_footer()
                await pilot.pause()
                self.assertEqual(footer._last_status_args["mcp_active"], 1)
                self.assertEqual(footer._last_status_args["mcp_total"], 4)

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

    async def test_subagent_footer_mount_unmount_and_update(self):
        from widgets.presentation.widgets.subagent_footer import SubagentStatusFooter

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
            self.assertEqual(footer.session, sess)
            self.assertIsNotNone(footer._last_grid_rows)

            # Test on_unmount cleans up resize timer
            footer.on_unmount()
            self.assertIsNone(footer._resize_timer)

    async def test_subagent_footer_old_session_fallback_metrics(self):
        from widgets.presentation.widgets.subagent_footer import SubagentStatusFooter

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
            self.assertEqual(footer.session, sess)
            self.assertIsNotNone(footer._last_grid_rows)

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
            "worktree:subagent-123",
        )
        # Deep nested worktree truncation
        self.assertEqual(
            format_display_path(
                os.path.join(home, ".johnston", "worktrees", "subagent-123", "pkg", "mod"),
                max_length=25,
            ),
            "worktree:.../mod",
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

    def test_compute_branch_sync_bare_branch(self):
        footer = StatusFooter()
        with patch("core.application.generation.prompt_builder.get_git_info", return_value="main"):
            self.assertEqual(footer._compute_branch_sync(cwd="/some/dir"), "main")

    def test_compute_branch_sync_detached_head(self):
        footer = StatusFooter()
        with patch("core.application.generation.prompt_builder.get_git_info", return_value="detached HEAD (abc1234)"):
            self.assertEqual(footer._compute_branch_sync(cwd="/some/dir"), "detached (abc1234)")

    def test_compute_branch_sync_not_repo(self):
        footer = StatusFooter()
        with patch("core.application.generation.prompt_builder.get_git_info", return_value=""):
            self.assertEqual(footer._compute_branch_sync(cwd="/some/dir"), "")

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
            row2_right = rows[1][1]
            self.assertIn("⚡", row2_right)
            self.assertIn("1 agent", row2_right)
            self.assertIn("2 shell", row2_right)

    async def test_update_status_background_label_empty(self):
        app = FooterTestApp()
        async with app.run_test():
            footer = app.query_one(StatusFooter)
            footer.update_status(provider_key="openai", model_name="gpt-4o")
            rows = footer._last_grid_rows
            self.assertEqual(rows[1][1], "")

    async def test_attachment_bar_updates(self):
        from widgets.presentation.widgets.attachment_bar import AttachmentBar, AttachmentChip, AttachmentHint

        bar = AttachmentBar()
        bar.update_attachments([])
        self.assertEqual(bar.styles.display, "none")

        mock_att = MagicMock(path="/tmp/test_image.png")
        bar.update_attachments([mock_att])
        self.assertEqual(bar.styles.display, "block")

        chip = AttachmentChip(mock_att, index=1)
        self.assertIn("Image #1", str(chip.render()))
        self.assertIn("\u00a0×", str(chip.render()))

        chip2 = AttachmentChip(mock_att, index=2)
        self.assertIn("Image #2", str(chip2.render()))

        hint = AttachmentHint()
        self.assertIn("ctrl+d", str(hint.render()))
        self.assertIn("to detach", str(hint.render()))
        self.assertIn("(", str(hint.render()))
        self.assertIn(")", str(hint.render()))

        # Test single chip click calls remove_clipboard_attachment
        mock_ci = MagicMock()
        mock_app = MagicMock()
        mock_app.query_one.return_value = mock_ci
        with patch.object(AttachmentChip, "app", new=mock_app):
            chip.on_click()
        mock_ci.remove_clipboard_attachment.assert_called_once_with(mock_att)

    async def test_generating_interrupt_hint(self):
        app = FooterTestApp()
        async with app.run_test():
            footer = app.query_one(StatusFooter)

            # Not generating -> no interrupt hint
            footer.is_generating = False
            footer.update_status(provider_key="openai", model_name="gpt-4o")
            rows = footer._last_grid_rows
            self.assertNotIn("to interrupt", rows[0][0])

            # Generating -> interrupt hint present
            footer.is_generating = True
            footer.update_status(provider_key="openai", model_name="gpt-4o")
            rows = footer._last_grid_rows
            self.assertIn("esc", rows[0][0])
            self.assertIn("to interrupt", rows[0][0])
            self.assertIn("(", rows[0][0])
            self.assertIn(")", rows[0][0])





