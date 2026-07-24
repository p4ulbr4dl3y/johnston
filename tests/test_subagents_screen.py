import unittest
from unittest.mock import patch

from core.subagent_registry import SubagentDefinition, SubagentRegistry
from core.subagent_tracker import SubagentSessionData, SubagentTracker
from widgets.screens.subagents import SubagentsScreen


class TestSubagentsScreen(unittest.TestCase):
    def test_subagents_screen_initialization_and_tab_switch(self):
        sess1 = SubagentSessionData(
            task_id="test-task-1",
            description="Test execution task",
            prompt="Run test",
            subagent_type="general",
            background=False
        )
        tmpl1 = SubagentDefinition(
            name="custom_tmpl",
            description="Custom subagent template",
            system_prompt="Test prompt"
        )

        with patch.object(SubagentTracker, "get_sessions_for_session", return_value=[sess1]):
            with patch.object(SubagentRegistry, "list_definitions", return_value={"custom_tmpl": tmpl1}):
                screen = SubagentsScreen()
                screen.sessions = [sess1]
                screen.templates = [tmpl1]
                self.assertEqual(screen.active_tab, 0)
                self.assertIn("Active Tasks", screen._get_header_title())

                # Toggle tab
                screen.active_tab = 1
                self.assertIn("Subagent Templates", screen._get_header_title())


if __name__ == "__main__":
    unittest.main()
