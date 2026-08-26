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
        from rich.text import Text

        long_title = "исследуй реализацию skill manager, насколько сделано чи..."
        sessions = [
            {"id": "p1", "title": long_title, "message_count": 55},
            {"id": "c1", "parent_id": "p1", "title": long_title, "message_count": 14},
        ]
        screen = ResumeScreen(sessions)
        plain_p = Text.from_markup(screen.raw_options[0]).plain
        plain_c = Text.from_markup(screen.raw_options[1]).plain

        # The trailing '...' of the title before the spaces/badge must end at identical index
        dots_pos_p = plain_p.find("...")
        dots_pos_c = plain_c.find("...")
        self.assertEqual(dots_pos_p, dots_pos_c)
