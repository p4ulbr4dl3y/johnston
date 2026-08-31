"""Tests for modal OptionList badge responsiveness across terminal widths.

Verifies that screens with two-column/badge OptionLists (ResumeScreen, RewindScreen,
ShellTasksScreen, SubagentsScreen, MCPScreen) dynamically adapt their row widths
on mount and resize so badges are never truncated on narrow screens.
"""
import unittest
from unittest.mock import MagicMock, patch

from textual import events

from core.application.session.actions import RewindEntry
from widgets.presentation.screens.mcp import MCPScreen
from widgets.presentation.screens.resume import ResumeScreen
from widgets.presentation.screens.rewind import RewindScreen
from widgets.presentation.screens.tasks import ShellTasksScreen, SubagentsScreen
from widgets.utils.row_format import display_width


class TestResumeScreenAdaptivity(unittest.TestCase):
    def setUp(self):
        self.sessions = [
            {"id": "sess-1", "title": "First session with a very long title that needs truncation", "message_count": 62},
            {"id": "sess-2", "title": "Short title", "message_count": 1},
            {"id": "sess-3", "title": "Zero steps session", "message_count": 0},
        ]

    def test_init_formats_options(self):
        screen = ResumeScreen(self.sessions, current_session_id="sess-1")
        self.assertEqual(len(screen.raw_options), 3)
        self.assertIn("62 steps", screen.raw_options[0])
        self.assertIn("1 step", screen.raw_options[1])
        self.assertIn("0 steps", screen.raw_options[2])

    def test_refresh_options_adapts_to_narrow_width(self):
        screen = ResumeScreen(self.sessions, current_session_id="sess-1")
        opt_list = MagicMock()
        opt_list.size.width = 46  # 46 - 2 = 44 usable row width
        opt_list.highlighted = 0
        screen.query_one = MagicMock(return_value=opt_list)

        screen._refresh_options()

        # Check that row width was adapted to 44
        self.assertEqual(len(screen.raw_options), 3)
        row0 = screen.raw_options[0]
        # Must contain badge and not exceed 44 visible width
        self.assertIn("62 steps", row0)
        from rich.text import Text
        plain = Text.from_markup(row0).plain
        self.assertEqual(display_width(plain), 44)

    def test_on_resize_triggers_reformat(self):
        screen = ResumeScreen(self.sessions, current_session_id="sess-1")
        screen._refresh_options = MagicMock()
        screen._apply_dialog_fit = MagicMock()

        resize_event = MagicMock(spec=events.Resize)
        screen.on_resize(resize_event)

        screen._refresh_options.assert_called_once()
        screen._apply_dialog_fit.assert_called_once()


class TestRewindScreenAdaptivity(unittest.TestCase):
    def setUp(self):
        self.messages = [
            RewindEntry(index=0, text="First user query about responsive UI layout", git_stats="2 files (+10 -2)"),
            RewindEntry(index=1, text="Second short message", git_stats=""),
        ]

    def test_init_formats_step1_options(self):
        screen = RewindScreen(self.messages, checkpoints_enabled=True)
        self.assertEqual(len(screen.raw_options), 3)
        self.assertIn("2 files (+10 -2)", screen.raw_options[0])
        self.assertIn("no checkpoint", screen.raw_options[1])
        self.assertIn("Current state", screen.raw_options[2])

    def test_refresh_step1_adapts_to_narrow_width(self):
        screen = RewindScreen(self.messages, checkpoints_enabled=True)
        opt_list = MagicMock()
        opt_list.size.width = 50  # 50 - 2 = 48 usable width
        opt_list.highlighted = 0
        screen.query_one = MagicMock(return_value=opt_list)

        screen._refresh_options()

        from rich.text import Text
        plain0 = Text.from_markup(screen.raw_options[0]).plain
        self.assertEqual(display_width(plain0), 48)
        self.assertIn("2 files (+10 -2)", plain0)

    def test_on_resize_refreshes_step1_and_step2(self):
        screen = RewindScreen(self.messages, checkpoints_enabled=True)
        screen._refresh_options = MagicMock()

        screen.on_resize(MagicMock(spec=events.Resize))
        screen._refresh_options.assert_called_once()

        # RewindActionScreen formats options with badge row
        from widgets.presentation.screens.rewind_action import RewindActionScreen

        action_screen = RewindActionScreen(self.messages[0])
        action_screen._apply_dialog_fit = MagicMock()
        action_screen._update_files_display = MagicMock()

        action_screen.on_resize(MagicMock(spec=events.Resize))
        action_screen._apply_dialog_fit.assert_called_once()
        action_screen._update_files_display.assert_called_once()
        self.assertEqual(len(action_screen.options), 3)
        self.assertIn("keep current code", action_screen.options[0])
        self.assertIn("restore code", action_screen.options[1])


class TestTasksScreenAdaptivity(unittest.TestCase):
    def test_on_resize_invalidates_signatures_and_updates(self):
        screen = ShellTasksScreen()
        screen.update_tasks_list = MagicMock()
        screen._last_signatures = [("t1", True, "cmd", "running", 78)]

        screen.on_resize(MagicMock(spec=events.Resize))

        self.assertIsNone(screen._last_signatures)
        screen.update_tasks_list.assert_called_once()

    def test_subagents_screen_on_resize(self):
        screen = SubagentsScreen()
        screen.update_tasks_list = MagicMock()
        screen._last_signatures = [("s1", True, "subagent", "running", 78)]

        screen.on_resize(MagicMock(spec=events.Resize))

        self.assertIsNone(screen._last_signatures)
        screen.update_tasks_list.assert_called_once()


class TestMCPScreenAdaptivity(unittest.TestCase):
    @patch("widgets.presentation.screens.mcp.get_mcp_manager")
    def test_on_resize_renders_from_cache_when_mounted(self, mock_get_mm):
        screen = MCPScreen()
        screen._render_from_cache = MagicMock()

        with patch.object(MCPScreen, "is_mounted", True):
            screen.on_resize(MagicMock(spec=events.Resize))
            screen._render_from_cache.assert_called_once()


if __name__ == "__main__":
    unittest.main()
