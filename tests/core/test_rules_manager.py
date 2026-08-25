import os
import tempfile
import unittest

from core.application.rules.rules import RuleDefinition, RulesManager


class TestRulesManager(unittest.TestCase):
    def test_rule_definition_basic(self):
        rule = RuleDefinition("rule1", "Content 1")
        self.assertEqual(rule.name, "rule1")
        self.assertEqual(rule.content, "Content 1")
        self.assertEqual(rule.source, "global")

    def test_load_markdown_rules_with_heading(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = os.path.join(tmpdir, ".johnston", "rules")
            os.makedirs(rules_dir, exist_ok=True)

            with open(os.path.join(rules_dir, "rule1.md"), "w", encoding="utf-8") as f:
                f.write("""# Python UV
Always run uv instead of pip.""")

            rm = RulesManager()
            rules = rm.load_rules(project_dir=tmpdir, include_global=False)
            self.assertEqual(len(rules), 1)

            rule = rules[0]
            self.assertEqual(rule.name, "Python UV")
            self.assertEqual(rule.content, "Always run uv instead of pip.")
            active_rules = rm.get_active_rules(project_dir=tmpdir, include_global=False)
            self.assertEqual(len(active_rules), 1)
            self.assertEqual(active_rules[0].name, "Python UV")

    def test_load_markdown_rules_without_heading(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            rules_dir = os.path.join(tmpdir, ".johnston", "rules")
            os.makedirs(rules_dir, exist_ok=True)

            with open(os.path.join(rules_dir, "my_custom_rule.md"), "w", encoding="utf-8") as f:
                f.write("Just some instructions without header.")

            rm = RulesManager()
            rules = rm.load_rules(project_dir=tmpdir, include_global=False)
            self.assertEqual(len(rules), 1)

            rule = rules[0]
            self.assertEqual(rule.name, "my_custom_rule")
            self.assertEqual(rule.content, "Just some instructions without header.")

    def test_deduplicate_when_global_and_project_paths_match(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            from unittest.mock import patch

            rules_dir = os.path.join(tmpdir, "rules")
            os.makedirs(rules_dir, exist_ok=True)
            with open(os.path.join(rules_dir, "rule1.md"), "w", encoding="utf-8") as f:
                f.write("Rule text")

            rm = RulesManager()
            with patch("core.infrastructure.runtime.markdown_scanner.CONFIG_DIR", tmpdir):
                proj_rules_dir = os.path.join(tmpdir, ".johnston", "rules")
                os.makedirs(os.path.dirname(proj_rules_dir), exist_ok=True)
                os.symlink(rules_dir, proj_rules_dir)

                rules = rm.load_rules(project_dir=tmpdir, include_global=True)
                self.assertEqual(len(rules), 1)
                self.assertEqual(rules[0].source, "global")

    def test_markdown_scanner_cache_ttl_skips_signature(self):
        from unittest.mock import patch

        from core.infrastructure.runtime.markdown_scanner import MarkdownScannerCache

        cache = MarkdownScannerCache(subpath="rules")
        with tempfile.TemporaryDirectory() as tmpdir:
            res1 = cache.get(project_dir=tmpdir, include_global=False)
            with patch("core.infrastructure.runtime.markdown_scanner.compute_dir_signature", side_effect=AssertionError("Should not compute signature within TTL")):
                res2 = cache.get(project_dir=tmpdir, include_global=False)
                self.assertEqual(res1, res2)


if __name__ == "__main__":
    unittest.main()
