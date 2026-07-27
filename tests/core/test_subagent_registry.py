import os
import tempfile
import unittest

from core.subagent_registry import SubagentRegistry


class TestSubagentRegistry(unittest.TestCase):
    def test_default_definitions(self):
        registry = SubagentRegistry.get_instance()
        defs = registry.list_definitions()
        self.assertIn("explore", defs)
        self.assertIn("general", defs)

        explore_def = registry.get_definition("explore")
        self.assertEqual(explore_def.name, "explore")
        self.assertIn("[SUBAGENT EXPLORE MODE]", explore_def.system_prompt)

    def test_load_markdown_and_json_subagents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_subagents = os.path.join(tmpdir, ".johnston", "subagents")
            os.makedirs(proj_subagents, exist_ok=True)

            # 1. Create a markdown subagent definition
            md_file = os.path.join(proj_subagents, "reviewer.md")
            with open(md_file, "w", encoding="utf-8") as f:
                f.write("""---
name: reviewer
description: Code reviewer subagent
tools: read, grep, glob
model: deepseek-v4-flash
---
You are a senior code reviewer subagent. Analyze diffs carefully.""")

            # 2. Create a JSON subagent definition
            json_file = os.path.join(proj_subagents, "tester.json")
            with open(json_file, "w", encoding="utf-8") as f:
                f.write("""{
  "name": "tester",
  "description": "Automated testing subagent",
  "system_prompt": "You run tests and report coverage.",
  "tools": ["shell"],
  "model": "gpt-4o"
}""")

            registry = SubagentRegistry()
            registry.reload(project_dir=tmpdir)
            defs = registry.list_definitions()

            self.assertIn("reviewer", defs)
            self.assertIn("tester", defs)

            reviewer_def = registry.get_definition("reviewer")
            self.assertEqual(reviewer_def.description, "Code reviewer subagent")
            self.assertEqual(reviewer_def.tools, ["read", "grep", "glob"])
            self.assertEqual(reviewer_def.model, "deepseek-v4-flash")
            self.assertIn("senior code reviewer", reviewer_def.system_prompt)

            tester_def = registry.get_definition("tester")
            self.assertEqual(tester_def.description, "Automated testing subagent")
            self.assertEqual(tester_def.tools, ["shell"])
            self.assertEqual(tester_def.model, "gpt-4o")


if __name__ == "__main__":
    unittest.main()
