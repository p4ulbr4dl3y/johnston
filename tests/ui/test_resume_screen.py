import unittest

from widgets.presentation.screens.resume import ResumeScreen, _order_sessions_hierarchically


class TestResumeScreen(unittest.TestCase):
    def test_order_sessions_hierarchically(self):
        sessions = [
            {"id": "p1", "title": "Parent 1"},
            {"id": "p2", "title": "Parent 2"},
            {"id": "c1", "parent_id": "p1", "title": "Child 1 of P1"},
            {"id": "c2", "parent_id": "p1", "title": "Child 2 of P1"},
        ]
        ordered = _order_sessions_hierarchically(sessions)
        ordered_ids = [s["id"] for s in ordered]
        self.assertEqual(ordered_ids, ["p1", "c1", "c2", "p2"])

    def test_resume_screen_fork_branch_prefix(self):
        from rich.cells import cell_len
        from rich.text import Text

        sessions = [
            {"id": "p1", "title": "Parent 1", "message_count": 5},
            {"id": "c1", "parent_id": "p1", "title": "Fork of P1", "message_count": 2},
        ]
        screen = ResumeScreen(sessions)
        self.assertEqual(len(screen.raw_options), 2)
        self.assertNotIn("└─", screen.raw_options[0])
        self.assertIn("└─", screen.raw_options[1])
        self.assertIn("Fork of P1", screen.raw_options[1])

        # Both parent and fork rows must have identical visible cell width for flush-right alignment
        len_p = cell_len(Text.from_markup(screen.raw_options[0]).plain)
        len_c = cell_len(Text.from_markup(screen.raw_options[1]).plain)
        self.assertEqual(len_p, len_c)

    def test_resume_screen_fork_ellipsis_alignment(self):
        from rich.cells import cell_len
        from rich.text import Text

        long_title = "исследуй реализацию skill manager, насколько сделано чисто и модульно в проекте" * 2
        sessions = [
            {"id": "p1", "title": long_title, "message_count": 55},
            {"id": "c1", "parent_id": "p1", "title": long_title, "message_count": 14},
        ]
        screen = ResumeScreen(sessions)
        len_p = cell_len(Text.from_markup(screen.raw_options[0]).plain)
        len_c = cell_len(Text.from_markup(screen.raw_options[1]).plain)
        self.assertEqual(len_p, len_c)
        self.assertIn("55 steps", screen.raw_options[0])
        self.assertIn("14 steps", screen.raw_options[1])

    def test_resume_screen_initial_selected_id(self):
        sessions = [
            {"id": "s1", "title": "Active Session", "message_count": 5},
            {"id": "s2", "title": "Target Session", "message_count": 2},
        ]
        screen = ResumeScreen(sessions, current_session_id="s1", initial_selected_id="s2")
        self.assertEqual(screen.default_value, "s2")
        self.assertEqual(screen.current_session_id, "s1")
        self.assertTrue(screen.raw_options[0].startswith("● "))
        self.assertTrue(screen.raw_options[1].startswith("  "))

    def test_resume_screen_step2_locked_transition(self):
        from unittest.mock import MagicMock

        from textual.widgets import OptionList

        sessions = [
            {"id": "s1", "title": "Free Session", "message_count": 2, "is_locked": False},
            {"id": "s2", "title": "Locked Session", "message_count": 5, "is_locked": True},
        ]
        screen = ResumeScreen(sessions)
        screen.dismiss = MagicMock()

        # Step 1: select unlocked session -> dismiss with sid
        ev1 = MagicMock(spec=OptionList.OptionSelected)
        ev1.option_index = 0
        screen.on_option_list_option_selected(ev1)
        screen.dismiss.assert_called_once_with("s1")

        # Step 1: select locked session -> enter Step 2
        screen.dismiss.reset_mock()
        screen.query_one = MagicMock()
        ev2 = MagicMock(spec=OptionList.OptionSelected)
        ev2.option_index = 1
        screen.on_option_list_option_selected(ev2)
        self.assertEqual(screen.step, 2)
        screen.dismiss.assert_not_called()
        self.assertEqual(screen.filtered_items, ["readonly", "steal"])

        # Step 2: select steal -> dismiss with steal:s2
        ev_steal = MagicMock(spec=OptionList.OptionSelected)
        ev_steal.option_index = 1
        screen.on_option_list_option_selected(ev_steal)
        screen.dismiss.assert_called_once_with("steal:s2")

        # Step 2: esc -> back to Step 1
        screen._show_step_2(sessions[1])
        self.assertEqual(screen.step, 2)
        esc_event = MagicMock(key="escape")
        screen._on_key(esc_event)
        self.assertEqual(screen.step, 1)
        self.assertEqual(screen.filtered_items, ["s1", "s2"])

        # Test on_input_submitted on locked session
        opt_list = MagicMock()
        opt_list.highlighted = 1
        screen.query_one = MagicMock(return_value=opt_list)
        input_ev = MagicMock()
        screen.on_input_submitted(input_ev)
        self.assertEqual(screen.step, 2)

