import os
import tempfile
import unittest

from core.subagent_registry import SubagentRegistry
from core.subagent_tracker import SubagentTracker


class TestSubagentRegistry(unittest.TestCase):
    def test_default_definitions(self):
        registry = SubagentRegistry.get_instance()
        defs = registry.list_definitions()
        self.assertIn("explorer", defs)
        self.assertIn("worker", defs)

        explorer_def = registry.get_definition("explorer")
        self.assertEqual(explorer_def.name, "explorer")
        self.assertIn("## Subagent Type: EXPLORER", explorer_def.system_prompt)

    def test_load_markdown_subagents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_subagents = os.path.join(tmpdir, ".johnston", "subagents")
            os.makedirs(proj_subagents, exist_ok=True)

            # 1. Create reviewer subagent definition
            md_file = os.path.join(proj_subagents, "reviewer.md")
            with open(md_file, "w", encoding="utf-8") as f:
                f.write("""---
name: reviewer
description: Code reviewer subagent
tools: read, grep, glob
model: deepseek-v4-flash
---
You are a senior code reviewer subagent. Analyze diffs carefully.""")

            # 2. Create tester subagent definition
            md_file2 = os.path.join(proj_subagents, "tester.md")
            with open(md_file2, "w", encoding="utf-8") as f:
                f.write("""---
name: tester
description: Automated testing subagent
tools: shell
model: gpt-4o
---
You run tests and report coverage.""")

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
            self.assertIn("run tests and report coverage", tester_def.system_prompt)

            snippet = registry.get_system_prompt_snippet(project_dir=tmpdir)
            self.assertIn("## Subagents (use as `subagent_type` in `invoke_subagent`)", snippet)
            self.assertIn("### Builtin", snippet)
            self.assertIn("- `explorer`: Fast code exploration subagent", snippet)
            self.assertIn("### Project (`.johnston/subagents/<name>.md`)", snippet)
            self.assertIn("- `reviewer`: Code reviewer subagent (Tools: read, grep, glob)", snippet)


class TestSubagentTrackerStrictMatch(unittest.IsolatedAsyncioTestCase):
    """A vague/non-matching identifier must NOT fall back to the last session — that
    would risk killing or inspecting the wrong subagent."""

    def setUp(self):
        self.tracker = SubagentTracker.get_instance()
        self.tracker.sessions.clear()

    def tearDown(self):
        self.tracker.sessions.clear()

    async def test_no_loose_fallback_for_unknown_id(self):
        self.tracker.create_session("task-1", "Important task", "p1", "worker", False)
        self.tracker.create_session("task-2", "Other task", "p2", "worker", False)

        # A single letter that previously matched via substring must now return None.
        self.assertIsNone(self.tracker.find_session_by_description_or_id("a"))
        # A totally unknown id must return None, not the last session.
        self.assertIsNone(self.tracker.find_session_by_description_or_id("nonexistent-xyz"))

    async def test_exact_match_still_works(self):
        self.tracker.create_session("task-1", "Important task", "p1", "worker", False)
        res = self.tracker.find_session_by_description_or_id("task-1")
        self.assertIsNotNone(res)
        self.assertEqual(res.task_id, "task-1")
        res = self.tracker.find_session_by_description_or_id("Important task")
        self.assertIsNotNone(res)
        self.assertEqual(res.task_id, "task-1")


if __name__ == "__main__":
    unittest.main()


