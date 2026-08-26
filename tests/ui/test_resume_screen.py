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
