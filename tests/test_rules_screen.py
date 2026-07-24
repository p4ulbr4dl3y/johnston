import unittest
from unittest.mock import patch

from core.rules_manager import RuleDefinition, RulesManager
from widgets.screens.rules import RulesScreen


class TestRulesScreen(unittest.TestCase):
    def test_rules_screen_loads_and_formats_items(self):
        rule1 = RuleDefinition(
            name="test_global",
            content="# Global Rule\nSome content",
            description="Global test rule description",
            modes=["action"],
            source="global"
        )
        rule2 = RuleDefinition(
            name="test_project",
            content="Project rule content",
            modes=[],
            source="project"
        )

        with patch.object(RulesManager, "load_rules", return_value=[rule1, rule2]):
            screen = RulesScreen()
            screen.rules = [rule1, rule2]
            self.assertEqual(len(screen.rules), 2)
            self.assertEqual(screen.rules[0].name, "test_global")
            self.assertEqual(screen.rules[1].source, "project")


if __name__ == "__main__":
    unittest.main()
