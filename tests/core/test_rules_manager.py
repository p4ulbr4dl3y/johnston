import os
import tempfile
import unittest

from core.rules_manager import RuleDefinition, RulesManager


class TestRulesManager(unittest.TestCase):
    def test_rule_mode_and_glob_matching(self):
        rule_all = RuleDefinition("rule1", "Content 1")
        self.assertTrue(rule_all.is_active_for_mode("action"))
        self.assertTrue(rule_all.is_active_for_mode("explore"))
        self.assertTrue(rule_all.is_active_for_files(["main.py"]))

        rule_action = RuleDefinition("rule2", "Content 2", modes=["action"], globs=["*.py"])
        self.assertTrue(rule_action.is_active_for_mode("action"))
        self.assertFalse(rule_action.is_active_for_mode("explore"))
        self.assertTrue(rule_action.is_active_for_files(["app/main.py"]))
        self.assertFalse(rule_action.is_active_for_files(["README.md"]))

    def test_load_markdown_rules(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = os.path.join(tmpdir, ".johnston", "rules")
            os.makedirs(rules_dir, exist_ok=True)

            with open(os.path.join(rules_dir, "rule1.md"), "w", encoding="utf-8") as f:
                f.write("""---
name: python_uv
description: Use uv package manager
mode: action, explore
globs: "*.py"
---
Always run uv instead of pip.""")

            rm = RulesManager()
            rules = rm.load_rules(project_dir=tmpdir, include_global=False)
            self.assertEqual(len(rules), 1)

            rule = rules[0]
            self.assertEqual(rule.name, "python_uv")
            self.assertEqual(rule.modes, ["action", "explore"])
            self.assertEqual(rule.globs, ["*.py"])
            self.assertIn("Always run uv instead of pip.", rule.content)

            formatted = rm.get_formatted_rules(mode="action", changed_files=["main.py"], project_dir=tmpdir)
            self.assertIn("### Rule: python_uv", formatted)
            self.assertIn("Always run uv instead of pip.", formatted)

    def test_deduplicate_when_global_and_project_paths_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from unittest.mock import patch
            rules_dir = os.path.join(tmpdir, "rules")
            os.makedirs(rules_dir, exist_ok=True)
            with open(os.path.join(rules_dir, "rule1.md"), "w", encoding="utf-8") as f:
                f.write("Rule text")

            rm = RulesManager()
            with patch("core.rules_manager.CONFIG_DIR", tmpdir):
                proj_rules_dir = os.path.join(tmpdir, ".johnston", "rules")
                os.makedirs(os.path.dirname(proj_rules_dir), exist_ok=True)
                os.symlink(rules_dir, proj_rules_dir)

                rules = rm.load_rules(project_dir=tmpdir, include_global=True)
                self.assertEqual(len(rules), 1)
                self.assertEqual(rules[0].source, "global")


if __name__ == "__main__":
    unittest.main()
