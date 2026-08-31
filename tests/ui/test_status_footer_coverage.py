import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from widgets.presentation.widgets.footer_layout import format_display_path
from widgets.presentation.widgets.subagent_footer import SubagentHeader, SubagentStatusFooter
from widgets.status_footer import StatusFooter


class FooterHarness(StatusFooter):
    def __init__(self, width=120, app=None):
        super().__init__()
        self._harness_app = app
        self._harness_width = width
        self.last_update = None

    @property
    def app(self):
        return self._harness_app

    @property
    def size(self):
        return SimpleNamespace(width=self._harness_width, height=2)

    def update(self, markup):
        self.last_update = markup


_mcp_mgr_patch = "core.infrastructure.mcp.get_mcp_manager"


class TestStatusFooterCoverage(unittest.TestCase):
    @pytest.mark.skipif(os.name == "nt", reason="Windows symlink resolution requires target existence and special privileges")
    def test_format_display_path_symlink_into_home(self):
        home = os.path.realpath(os.path.expanduser("~"))
        target = os.path.join(home, "johnston")
        with tempfile.TemporaryDirectory() as tmp:
            link = os.path.join(tmp, "link")
            try:
                os.symlink(target, link)
            except OSError:
                self.skipTest("symlink not supported")
            res = format_display_path(link)
            self.assertEqual(res, "~/johnston")

    @pytest.mark.skipif(os.name == "nt", reason="expects POSIX-style separators")
    def test_format_display_path_len_three_parts(self):
        self.assertEqual(format_display_path("/aa/bb", max_length=3), "/.../bb")

    def test_format_display_path_worktree_exact_and_long(self):
        from core.infrastructure.platform.paths import WORKTREES_DIR

        # Exact worktree dir
        self.assertEqual(format_display_path(WORKTREES_DIR), "worktree")
        # Subpath under WORKTREES_DIR
        subpath = os.path.join(WORKTREES_DIR, "subagent-16ab6b")
        self.assertEqual(format_display_path(subpath), "worktree:subagent-16ab6b")
        # Very long worktree name truncated
        long_wt = os.path.join(WORKTREES_DIR, "subagent-super-long-identifier-1234567890")
        res = format_display_path(long_wt, max_length=20)
        self.assertTrue(res.startswith("worktree:"))
        self.assertLessEqual(len(res), 20)

    def test_format_display_path_exception_returns_raw(self):
        with patch("os.path.abspath", side_effect=Exception("boom")):
            self.assertEqual(format_display_path("/my/path"), "/my/path")

    def test_status_footer_no_pm_and_bad_app_size(self):
        footer = FooterHarness()
        footer._harness_app = None
        with patch("widgets.status_footer.catalog.get_model_display_name", return_value=""):
            footer.update_status(provider_key="openai", is_connected=None, model_name="")
        self.assertIsNotNone(footer.last_update)
        self.assertIsNotNone(footer._last_grid_rows)

        # app.size raises -> fallback app_width
        class BadApp:
            @property
            def size(self):
                raise Exception("no size")

        footer._harness_app = BadApp()
        footer.update_status(provider_key="openai", is_connected=True, model_name="")

    def test_set_generating_toggle_off(self):
        footer = FooterHarness()
        timer = MagicMock()
        footer._spinner_timer = timer
        footer.is_generating = True
        with patch.object(footer, "refresh_footer") as rf:
            footer.set_generating(False)
        timer.stop.assert_called_once()
        self.assertEqual(footer._spinner_idx, 0)
        rf.assert_called_once()

    def test_on_unmount_timer_stop_raises(self):
        footer = FooterHarness()
        stop_err = MagicMock()
        stop_err.stop.side_effect = Exception("boom")
        footer._spinner_timer = stop_err
        footer._mcp_poll_timer = stop_err
        footer._resize_timer = stop_err
        footer.on_unmount()
        self.assertIsNone(footer._spinner_timer)
        self.assertIsNone(footer._mcp_poll_timer)
        self.assertIsNone(footer._resize_timer)

    def test_on_resize_same_and_different(self):
        footer = FooterHarness()
        with patch.object(footer, "refresh_footer") as rf:
            footer._last_resize_size = "S"
            footer.on_resize(SimpleNamespace(size="S"))
            rf.assert_not_called()

        timer = MagicMock()
        footer._resize_timer = timer
        new_timer = MagicMock()
        footer.set_timer = MagicMock(return_value=new_timer)
        footer.on_resize(SimpleNamespace(size="T"))
        timer.stop.assert_called_once()
        self.assertIs(footer._resize_timer, new_timer)
        footer.set_timer.assert_called_once()

    def test_stream_frame_not_generating_returns(self):
        footer = FooterHarness()
        footer.is_generating = False
        footer._last_grid_rows = [["a"]]
        with patch.object(footer, "update") as upd:
            footer._render_stream_frame()
            upd.assert_not_called()

    def test_stream_frame_no_cached_rows_returns(self):
        footer = FooterHarness()
        footer.is_generating = True
        footer._last_grid_rows = None
        with patch.object(footer, "update") as upd:
            footer._render_stream_frame()
            upd.assert_not_called()

    def test_stream_frame_update_exception_suppressed(self):
        footer = FooterHarness()
        footer.is_generating = True
        footer._spinner_idx = 3
        footer._last_grid_rows = [["a b c"], ["d"]]
        with patch.object(footer, "update", side_effect=Exception("boom")):
            footer._render_stream_frame()  # must not raise

    def test_stream_frame_swap_no_bracket_returns_left(self):
        footer = FooterHarness()
        self.assertEqual(footer._swap_frame("no-bracket", "x"), "no-bracket")

    def test_update_status_compact_with_diff(self):
        footer = FooterHarness(width=40)
        with patch.object(footer, "_git_diff_stats", return_value="+5 / -2"), patch.object(
            footer, "_git_branch", return_value=""
        ):
            footer.update_status(provider_key="openai", is_connected=True, model_name="gpt-4o")
        rows = footer._last_grid_rows
        joined = " ".join(str(r) for r in rows)
        self.assertIn("+5 / -2", joined)

    def test_update_status_noncompact_with_diff(self):
        footer = FooterHarness()
        with patch.object(footer, "_git_diff_stats", return_value="+5 / -2"), patch.object(
            footer, "_git_branch", return_value=""
        ):
            footer.update_status(provider_key="openai", is_connected=False, model_name="")
        joined = " ".join(str(r) for r in footer._last_grid_rows)
        self.assertIn("+5 / -2", joined)


class TestSubagentStatusFooterCoverage(unittest.TestCase):
    def test_on_unmount_timer_stop_raises(self):
        footer = SubagentStatusFooter()
        timer = MagicMock()
        timer.stop.side_effect = Exception("boom")
        footer._spinner_timer = timer
        footer._resize_timer = timer
        footer.on_unmount()
        self.assertIsNone(footer._spinner_timer)
        self.assertIsNone(footer._resize_timer)

    def test_update_session_none_renders(self):
        footer = SubagentStatusFooter()
        footer._harness_app = MagicMock()
        with patch.object(footer, "update") as upd:
            footer.update_session(None)
        upd.assert_called_once()

    def test_update_session_running_and_completed(self):
        footer = SubagentStatusFooter()
        session = MagicMock()
        session.status = "running"
        session.agent = None
        session.role = "explorer"
        session.project_dir = "/tmp"
        session.branch_name = ""
        footer.set_interval = MagicMock(return_value=MagicMock())

        footer.update_session(session)
        self.assertTrue(footer.is_generating)
        self.assertIsNotNone(footer._spinner_timer)

        session.status = "completed"
        footer.update_session(session)
        self.assertFalse(footer.is_generating)
        self.assertIsNone(footer._spinner_timer)

    def test_spin_no_rows_renders(self):
        footer = SubagentStatusFooter()
        footer._last_grid_rows = None
        with patch.object(footer, "_render_footer") as rf:
            footer._spin()
        rf.assert_called_once()

    def test_spin_with_cached_rows(self):
        footer = SubagentStatusFooter()
        footer._last_grid_rows = [("left", "right")]
        with patch.object(footer, "_render_stream_frame") as rsf:
            footer._spin()
        rsf.assert_called_once()

    def test_render_footer_provider_active_and_pricing(self):
        footer = SubagentStatusFooter()
        footer._harness_app = MagicMock()
        session = MagicMock()
        session.agent = None
        session.role = "worker"
        session.project_dir = "/tmp"
        session.branch_name = ""
        session.messages = None
        session.last_context_tokens = 0
        session.total_tokens = 200
        session.cost_usd = 0.0
        session.title = "Test Subagent Task"

        app = MagicMock()
        cm = MagicMock()
        cm.get_active_provider_key.return_value = "openai"
        cm.load_providers.return_value = {}
        cm.is_provider_connected.return_value = False
        app.pm = cm
        footer._harness_app = app
        footer.session = session
        with patch("widgets.status_footer.catalog.get_model_display_name", return_value=""), patch(
            "widgets.status_footer.catalog.estimate_cost_from_totals", return_value=0.0,
        ), patch.object(footer, "_git_diff_stats", return_value=""):
            footer._render_footer()
        self.assertIsNotNone(footer._last_grid_rows)
        self.assertIn("Worker", footer._last_grid_rows[0][0])
        self.assertIn("[Select model: /models]", footer._last_grid_rows[0][0])
        self.assertIn("sandboxed", footer._last_grid_rows[1][0])
        self.assertIn("review", footer._last_grid_rows[1][0])
        self.assertIn("esc", footer._last_grid_rows[1][1])
        self.assertIn("close", footer._last_grid_rows[1][1])

    def test_render_footer_reflects_execution_mode_and_sandbox_off(self):
        from core.permission_manager import PermissionManager

        footer = SubagentStatusFooter()
        footer._harness_app = MagicMock()
        footer._harness_app.sandbox_enabled = False
        session = MagicMock()
        session.agent = None
        session.role = "worker"
        session.project_dir = "/tmp"
        session.branch_name = ""
        session.messages = None
        session.last_context_tokens = 0
        session.total_tokens = 100
        session.cost_usd = 0.0
        session.sandbox_enabled = False
        footer.session = session

        pm = PermissionManager.get_instance()
        orig_mode = pm.session_mode
        pm.set_session_mode("yolo")
        try:
            with patch("widgets.status_footer.catalog.get_model_display_name", return_value=""), patch(
                "widgets.status_footer.catalog.estimate_cost_from_totals", return_value=0.0,
            ), patch.object(footer, "_git_diff_stats", return_value=""):
                footer._render_footer()
            self.assertNotIn("sandboxed", footer._last_grid_rows[1][0])
            self.assertIn("yolo", footer._last_grid_rows[1][0])
        finally:
            pm.set_session_mode(orig_mode)

    def test_render_footer_compact_mode(self):
        footer = SubagentStatusFooter()
        session = MagicMock()
        session.agent = None
        session.role = "researcher"
        session.project_dir = "/tmp/my_repo"
        session.branch_name = "feat/test"
        session.messages = None
        session.last_context_tokens = 0
        session.total_tokens = 200
        session.cost_usd = 0.05
        session.title = "Compact Task Name Very Long"

        app = MagicMock()
        app.size = MagicMock(width=60)
        cm = MagicMock()
        cm.get_active_provider_key.return_value = "openai"
        cm.load_providers.return_value = {}
        cm.is_provider_connected.return_value = True
        app.pm = cm
        footer._harness_app = app
        footer.session = session
        with patch("widgets.status_footer.catalog.get_model_display_name", return_value="gpt-4o"), patch.object(
            footer, "_git_diff_stats", return_value="+2/-1"
        ):
            footer._render_footer()
        self.assertIsNotNone(footer._last_grid_rows)
        self.assertIn("gpt-4o", footer._last_grid_rows[0][0])
        self.assertIn("ctx", footer._last_grid_rows[0][1])
        self.assertIn("my_repo", footer._last_grid_rows[1][0])
        self.assertIn("sandboxed", footer._last_grid_rows[1][0])
        self.assertIn("esc", footer._last_grid_rows[1][1])

    def test_render_footer_sandbox_disabled(self):
        footer = SubagentStatusFooter()
        session = MagicMock()
        session.agent = None
        session.sandbox_enabled = False
        session.role = "worker"
        session.project_dir = "/tmp"
        session.branch_name = ""
        session.branch = ""
        session.messages = []
        session.last_context_tokens = 0
        session.total_tokens = 0
        session.cost_usd = 0.0

        app = MagicMock()
        app.size = MagicMock(width=100)
        app.agent = None
        app.subagent_registry = None
        app.bg_task_manager = None
        app.mcp_manager = None
        cm = MagicMock()
        cm.get_active_provider_key.return_value = "openai"
        cm.load_providers.return_value = {}
        cm.is_provider_connected.return_value = False
        app.pm = cm
        footer._harness_app = app
        footer.session = session
        with patch.object(footer, "_git_diff_stats", return_value=""):
            footer._render_footer()
        self.assertIsNotNone(footer._last_grid_rows)
        self.assertNotIn("sandboxed", footer._last_grid_rows[1][0])

    def test_render_footer_exception(self):
        footer = SubagentStatusFooter()
        session = MagicMock()
        session.agent = None
        session.role = "worker"
        session.project_dir = "/tmp"
        session.branch_name = ""
        session.messages = None
        footer.session = session
        bad_app = MagicMock()
        bad_app.agent = MagicMock()
        bad_app.pm = MagicMock()
        bad_app.pm.load_providers.side_effect = Exception("boom")
        footer._harness_app = bad_app
        footer._render_footer()  # exception swallowed


class TestSubagentHeaderCoverage(unittest.TestCase):
    def test_update_session_none_renders(self):
        header = SubagentHeader(from_tasks=True)
        header._harness_app = MagicMock()
        with patch.object(header, "update") as upd:
            header.update_session(None)
        upd.assert_called_once()
        self.assertIn("esc: back", header._last_grid_rows[0][1])

        header_close = SubagentHeader(from_tasks=False)
        header_close._harness_app = MagicMock()
        with patch.object(header_close, "update") as upd:
            header_close.update_session(None)
        upd.assert_called_once()
        self.assertIn("esc: close", header_close._last_grid_rows[0][1])

    def test_update_session_renders_title_only(self):
        header = SubagentHeader()
        header._harness_app = MagicMock()
        session = MagicMock()
        session.status = "running"
        session.agent = None
        session.role = "explorer"
        session.title = "Review feature"

        header.update_session(session)
        self.assertIn("Review feature", header._last_grid_rows[0][0])
        self.assertNotIn("Explorer:", header._last_grid_rows[0][0])

    def test_render_header_long_description_truncation(self):
        header = SubagentHeader(from_tasks=True)
        app = MagicMock()
        app.size = MagicMock(width=50)
        header._harness_app = app
        session = MagicMock()
        session.agent = None
        session.role = "worker"
        session.title = "A" * 100
        header.session = session
        header._render_header()
        self.assertTrue("..." in header._last_grid_rows[0][0] or "…" in header._last_grid_rows[0][0])

    def test_resize_debounced(self):
        header = SubagentHeader()
        event = MagicMock()
        event.size = MagicMock(width=100)
        header.set_timer = MagicMock(return_value=MagicMock())
        header.on_resize(event)
        self.assertIsNotNone(header._resize_timer)
        # same size no-op
        header.on_resize(event)
        # call debounced
        with patch.object(header, "_render_header") as rh:
            header._debounced_resize()
            rh.assert_called_once()
            self.assertIsNone(header._resize_timer)


# ---------------------------------------------------------------------------
# widgets/command_suggestions.py
# ---------------------------------------------------------------------------
