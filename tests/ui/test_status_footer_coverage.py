import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from widgets.status_footer import StatusFooter, SubagentStatusFooter, format_display_path


class FooterHarness(StatusFooter):
    def __init__(self, is_subagent=False, width=120, app=None):
        super().__init__(is_subagent=is_subagent)
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

    def test_poll_mcp_refresh_exception(self):
        footer = FooterHarness()
        with patch(_mcp_mgr_patch, side_effect=Exception("boom")):
            footer._poll_mcp_refresh()  # must not raise

    def test_active_mcp_count_exception(self):
        footer = FooterHarness()
        mgr = MagicMock()
        mgr.active_server_count.side_effect = Exception("boom")
        with patch(_mcp_mgr_patch, return_value=mgr):
            self.assertEqual(footer._active_mcp_count([]), 0)

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

    def test_spin_subagent_with_and_without_rows(self):
        sess = SimpleNamespace(status="running")
        footer = FooterHarness(is_subagent=True)
        footer._subagent_session = sess
        footer._last_grid_rows = [("a", "")]
        with patch.object(footer, "_render_stream_frame") as rsf, patch.object(
            footer, "update_subagent_footer"
        ) as usf:
            footer._spin()
            rsf.assert_called_once()

            footer._last_grid_rows = None
            footer._spin()
            usf.assert_called_once()

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

    def test_update_subagent_footer_running(self):
        agent = MagicMock()
        agent.role = "explorer"
        agent.thinking_effort = "high"
        agent.provider_key = "openai"
        agent.model = "gpt-4o"
        agent.get_metrics.return_value = {}
        agent.context_limit = 128000
        session = MagicMock()
        session.status = "running"
        session.branch_name = "feat"
        session.agent = agent
        session.project_dir = "/tmp/x"
        session.last_context_tokens = 0
        session.total_tokens = 0
        session.cost_usd = 0.0

        app = MagicMock()
        cm = MagicMock()
        cm.get_active_provider_key.return_value = "openai"
        cm.load_providers.return_value = {"openai": {"name": "OpenAI"}}
        cm.is_provider_connected.return_value = False
        app.pm = cm
        footer = FooterHarness(app=app)
        with patch("widgets.status_footer.catalog.get_model_display_name", return_value="GPT-4o"), patch.object(
            footer, "_git_diff_stats", return_value=""
        ), patch.object(footer, "set_interval", return_value=MagicMock()):
            footer.update_subagent_footer(session)
        self.assertTrue(footer.is_generating)
        self.assertIsNotNone(footer._last_grid_rows)

        # now switching to completed stops the spinner
        timer = MagicMock()
        session.status = "completed"
        footer.is_generating = True
        footer._spinner_timer = timer
        with patch("widgets.status_footer.catalog.get_model_display_name", return_value="GPT-4o"), patch.object(
            footer, "_git_diff_stats", return_value=""
        ):
            footer.update_subagent_footer(session)
        self.assertFalse(footer.is_generating)
        self.assertIsNone(footer._spinner_timer)

    def test_update_status_subagent_branch(self):
        footer = FooterHarness(is_subagent=True)
        with patch.object(footer, "_git_branch", return_value="main"), patch.object(
            footer, "_git_diff_stats", return_value=""
        ):
            footer.update_status(
                provider_key="openai",
                provider_display="OpenAI",
                clean_model="GPT-4o",
                is_connected=True,
                model_name="gpt-4o",
            )
        self.assertIsNotNone(footer._last_grid_rows)

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
        footer.on_unmount()
        self.assertIsNone(footer._spinner_timer)

    def test_update_session_none_renders(self):
        footer = SubagentStatusFooter()
        footer._harness_app = MagicMock()
        with patch.object(footer, "update") as upd:
            footer.update_session(None)
        upd.assert_called_once()

    def test_update_session_stops_spinner(self):
        footer = SubagentStatusFooter()
        footer.is_generating = True
        timer = MagicMock()
        footer._spinner_timer = timer
        session = MagicMock()
        session.status = "completed"
        session.agent = None
        session.role = "explorer"
        session.project_dir = "/tmp"
        session.branch_name = ""
        with patch.object(footer, "_render_footer") as rf:
            footer.update_session(session)
        self.assertFalse(footer.is_generating)
        timer.stop.assert_called_once()
        self.assertIsNone(footer._spinner_timer)
        rf.assert_called_once()

    def test_spin_no_rows_renders(self):
        footer = SubagentStatusFooter()
        footer._last_grid_rows = None
        with patch.object(footer, "_render_footer") as rf:
            footer._spin()
        rf.assert_called_once()

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

        app = MagicMock()
        cm = MagicMock()
        cm.get_active_provider_key.return_value = "openai"
        cm.load_providers.return_value = {}
        cm.is_provider_connected.return_value = False
        app.pm = cm
        footer._harness_app = app
        with patch("widgets.status_footer.catalog.get_model_display_name", return_value=""), patch(
            "widgets.status_footer.catalog.get_model_pricing",
            side_effect=lambda p, m: {"prompt": 1.0, "completion": 2.0} if p == "openai" else None,
        ), patch.object(footer, "_git_diff_stats", return_value=""):
            footer._render_footer()
        self.assertIsNotNone(footer._last_grid_rows)

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


# ---------------------------------------------------------------------------
# widgets/command_suggestions.py
# ---------------------------------------------------------------------------
