import unittest
from unittest.mock import patch

from core.subagent_tracker import SubagentSessionData, SubagentTracker
from widgets.screens.subagents import SubagentsScreen


class TestSubagentsScreen(unittest.TestCase):
    def test_subagents_screen_initialization(self):
        sess1 = SubagentSessionData(
            task_id="test-task-1",
            description="Test execution task",
            prompt="Run test",
            subagent_type="general",
            background=False
        )

        with patch.object(SubagentTracker, "get_sessions_for_session", return_value=[sess1]):
            screen = SubagentsScreen()
            screen.sessions = [sess1]
            self.assertEqual(len(screen.sessions), 1)
            self.assertEqual(screen.sessions[0].task_id, "test-task-1")


if __name__ == "__main__":
    unittest.main()

