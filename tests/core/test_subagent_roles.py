import os
import tempfile
import unittest

from core.role_registry import RoleRegistry
from core.session_manager import SessionStore


class TestSubagentRoles(unittest.TestCase):
    def test_default_definitions(self):
        registry = RoleRegistry.get_instance()
        defs = registry.list_subagent_roles()
        self.assertIn("explorer", defs)
        self.assertIn("worker", defs)

        explorer_def = registry.get_role("explorer")
        self.assertEqual(explorer_def.name, "Explorer")
        self.assertIn("## Execution Mode: EXPLORER", explorer_def.system_prompt)

    def test_load_markdown_subagents(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            proj_subagents = os.path.join(tmpdir, ".johnston", "roles")
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

            registry = RoleRegistry()
            registry.reload(project_dir=tmpdir)
            defs = registry.list_subagent_roles()

            self.assertIn("reviewer", defs)
            self.assertIn("tester", defs)

            reviewer_def = registry.get_role("reviewer")
            self.assertEqual(reviewer_def.description, "Code reviewer subagent")
            self.assertEqual(reviewer_def.allowed_tools, ["read", "grep", "glob"])
            self.assertEqual(reviewer_def.model, "deepseek-v4-flash")
            self.assertIn("senior code reviewer", reviewer_def.system_prompt)

            tester_def = registry.get_role("tester")
            self.assertEqual(tester_def.description, "Automated testing subagent")
            self.assertEqual(tester_def.allowed_tools, ["shell"])
            self.assertEqual(tester_def.model, "gpt-4o")
            self.assertIn("run tests and report coverage", tester_def.system_prompt)

            snippet = registry.get_system_prompt_snippet(project_dir=tmpdir)
            self.assertIn("## Subagents (use as `type` in `invoke_subagent`)", snippet)
            self.assertIn("### Builtin", snippet)
            self.assertIn("- `explorer`: Read-only Q&A, codebase research, and planning role.", snippet)
            self.assertIn("### Project (`.johnston/roles/<name>.md`)", snippet)
            self.assertIn("- `reviewer`: Code reviewer subagent (Tools: read, grep, glob)", snippet)


class TestSubagentRoleStrictMatch(unittest.IsolatedAsyncioTestCase):
    """A vague/non-matching identifier must NOT fall back to the last session — that
    would risk killing or inspecting the wrong subagent."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = SessionStore(project_path=self.temp_dir.name)
        self._old_instance = SessionStore._instance
        SessionStore._instance = self.store

    def tearDown(self):
        SessionStore._instance = self._old_instance

    def _mk(self, sid: str, desc: str, prompt: str):
        return self.store.create_subagent(
            parent_id="sess-main",
            subagent_id=sid,
            role="worker",
            description=desc,
            prompt=prompt,
            status="running",
        )

    async def test_no_loose_fallback_for_unknown_id(self):
        self._mk("task-1", "Important task", "p1")
        self._mk("task-2", "Other task", "p2")

        # A single letter that previously matched via substring must now return None.
        self.assertIsNone(self.store.find_session_by_description_or_id("a"))
        # A totally unknown id must return None, not the last session.
        self.assertIsNone(self.store.find_session_by_description_or_id("nonexistent-xyz"))

    async def test_exact_match_still_works(self):
        self._mk("task-1", "Important task", "p1")
        res = self.store.find_session_by_description_or_id("task-1")
        self.assertIsNotNone(res)
        self.assertEqual(res.id, "task-1")
        res = self.store.find_session_by_description_or_id("Important task")
        self.assertIsNotNone(res)
        self.assertEqual(res.id, "task-1")


if __name__ == "__main__":
    unittest.main()
