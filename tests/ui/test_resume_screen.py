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
        sessions = [
            {"id": "p1", "title": "Parent 1", "message_count": 5},
            {"id": "c1", "parent_id": "p1", "title": "Fork of P1", "message_count": 2},
        ]
        screen = ResumeScreen(sessions)
        self.assertEqual(len(screen.raw_options), 2)
        self.assertNotIn("└─", screen.raw_options[0])
        self.assertIn("└─", screen.raw_options[1])
        self.assertIn("Fork of P1", screen.raw_options[1])
