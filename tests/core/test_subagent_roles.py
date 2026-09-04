import os
import tempfile
import unittest

from core.infrastructure.storage.session_store import SessionStore
from core.role_registry import RoleRegistry


class TestSubagentRoles(unittest.TestCase):
    def test_default_definitions(self):
        registry = RoleRegistry.get_instance()
        defs = registry.list_subagent_roles()
        self.assertIn("explorer", defs)
        self.assertIn("worker", defs)

        explorer_def = registry.get_role("explorer")
        self.assertEqual(explorer_def.name, "Explorer")
        self.assertIn("Read-only", explorer_def.prompt)

    def test_format_role_prompt(self):
        from core.roles.prompt import format_role_prompt

        self.assertEqual(format_role_prompt("", ""), "")
        self.assertEqual(
            format_role_prompt("worker", "Do work."),
            '<role name="worker">\nDo work.\n</role>',
        )
        self.assertEqual(
            format_role_prompt("custom", '<role name="custom">\nAlready wrapped\n</role>'),
            '<role name="custom">\nAlready wrapped\n</role>',
        )
        self.assertEqual(
            format_role_prompt("", "No key role."),
            '<role>\nNo key role.\n</role>',
        )


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
allowed_tools: read, grep, glob
model: clinepass/deepseek-v4-flash
---
You are a senior code reviewer subagent. Analyze diffs carefully.""")

            # 2. Create tester subagent definition
            md_file2 = os.path.join(proj_subagents, "tester.md")
            with open(md_file2, "w", encoding="utf-8") as f:
                f.write("""---
name: tester
description: Automated testing subagent
allowed_tools: shell
model: gpt-4o
---
You run tests and report coverage.""")

            registry = RoleRegistry()
            registry.load_roles(project_dir=tmpdir)
            defs = registry.list_subagent_roles()

            self.assertIn("reviewer", defs)
            self.assertIn("tester", defs)

            reviewer_def = registry.get_role("reviewer")
            self.assertEqual(reviewer_def.description, "Code reviewer subagent")
            self.assertEqual(reviewer_def.allowed_tools, ["read", "grep", "glob"])
            self.assertEqual(reviewer_def.provider, "clinepass")
            self.assertEqual(reviewer_def.model, "deepseek-v4-flash")
            self.assertIn("senior code reviewer", reviewer_def.prompt)

            tester_def = registry.get_role("tester")
            self.assertEqual(tester_def.description, "Automated testing subagent")
            self.assertEqual(tester_def.allowed_tools, ["shell"])
            self.assertEqual(tester_def.provider, "")
            self.assertEqual(tester_def.model, "gpt-4o")
            self.assertIn("run tests and report coverage", tester_def.prompt)

            snippet = registry.get_system_prompt_snippet(project_dir=tmpdir)
            self.assertIn("- explorer (read-only): Read-only mode", snippet)
            self.assertIn(
                "- reviewer (tools: read, grep, glob, model: clinepass/deepseek-v4-flash): Code reviewer subagent",
                snippet,
            )
            self.assertIn(
                "- tester (tools: shell, model: gpt-4o): Automated testing subagent",
                snippet,
            )


class TestSubagentApplyRole(unittest.TestCase):
    def test_main_scope_role_falls_back_to_worker(self):
        """A main-only role must never run as a subagent; configure_subagent_agent
        must substitute the worker definition instead of using it verbatim."""
        import tempfile

        from core.application.session.stream import configure_subagent_agent
        from core.role_registry import RoleRegistry

        class _FakeAgent:
            pass

        with tempfile.TemporaryDirectory() as tmpdir:
            roles_dir = os.path.join(tmpdir, ".johnston", "roles")
            os.makedirs(roles_dir, exist_ok=True)
            with open(os.path.join(roles_dir, "lead.md"), "w", encoding="utf-8") as f:
                f.write("---\nname: Lead\nscope: main\n---\nLead prompt")

            registry = RoleRegistry()
            registry.load_roles(project_dir=tmpdir)
            definition = registry.get_role("lead")
            self.assertEqual(definition.scope, "main")
            agent = _FakeAgent()
            agent.tools = []
            configure_subagent_agent(agent, "lead", app=None, project_dir=tmpdir)
            # The subagent must end up bound to the worker role, not lead.
            self.assertEqual(agent.role, "worker")

    def test_configure_subagent_agent_with_worktree_branch(self):
        from core.application.session.stream import configure_subagent_agent

        class _FakeAgent:
            pass

        agent = _FakeAgent()
        agent.tools = []
        configure_subagent_agent(agent, "worker", app=None, worktree_branch="feat-branch")
        self.assertEqual(agent.worktree_branch, "feat-branch")
        self.assertIn("<worktree>", agent.system_prompt)
        self.assertIn("Branch: `feat-branch`", agent.system_prompt)



class TestSubagentApplyProvider(unittest.TestCase):
    def test_rebind_provider_in_place(self):
        """rebind_provider must swap provider fields onto the existing
        subagent object while preserving identity plumbing."""
        import types

        from core.roles.provider import rebind_provider

        class _FakeRebuilt:
            def __init__(self):
                self.provider_key = "clinepass"
                self.base_url = "https://api.cline.bot/api/v1"
                self.api_key = "sk-x"
                self.api_type = "openai"
                self.client = object()

        fake_pm = types.SimpleNamespace(
            create_agent_for_provider=lambda pk: _FakeRebuilt(),
        )

        class _FakeAgent:
            pass

        agent = _FakeAgent()
        agent.app = "APP"
        agent.is_subagent = True
        agent.tools = ["t1"]
        agent.provider_key = "openai"
        agent.base_url = "old"

        import unittest.mock as mock

        with mock.patch("core.provider_manager.ProviderManager", return_value=fake_pm):
            rebind_provider(agent, "clinepass")

        self.assertEqual(agent.provider_key, "clinepass")
        self.assertEqual(agent.base_url, "https://api.cline.bot/api/v1")
        self.assertEqual(agent.api_type, "openai")
        self.assertEqual(agent.app, "APP")
        self.assertEqual(agent.is_subagent, True)
        self.assertEqual(agent.tools, ["t1"])

    def test_rebind_provider_does_not_inject_magicmock(self):
        import types
        import unittest.mock as mock

        from core.base_provider import BaseAgent
        from core.roles.provider import rebind_provider

        real_rebuilt = BaseAgent(api_key="sk-new", model="gpt-4", base_url="http://new")
        fake_pm = types.SimpleNamespace(create_agent_for_provider=lambda pk: real_rebuilt)

        subagent = BaseAgent(api_key="sk-old", model="gpt-3.5", base_url="http://old")
        with mock.patch("core.provider_manager.ProviderManager", return_value=fake_pm):
            rebind_provider(subagent, "openai")

        self.assertIsNone(subagent._client)


class TestSubagentRoleStrictMatch(unittest.IsolatedAsyncioTestCase):

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
            title=desc,
            prompt=prompt,
            status="running",
        )

    async def test_no_loose_fallback_for_unknown_id(self):
        self._mk("task-1", "Important task", "p1")
        self._mk("task-2", "Other task", "p2")

        # A single letter that previously matched via substring must now return None.
        self.assertIsNone(self.store.find_session_by_title_or_id("a"))
        # A totally unknown id must return None, not the last session.
        self.assertIsNone(self.store.find_session_by_title_or_id("nonexistent-xyz"))

    async def test_exact_match_still_works(self):
        self._mk("task-1", "Important task", "p1")
        res = self.store.find_session_by_title_or_id("task-1")
        self.assertIsNotNone(res)
        self.assertEqual(res.id, "task-1")
        res = self.store.find_session_by_title_or_id("Important task")
        self.assertIsNotNone(res)
        self.assertEqual(res.id, "task-1")


if __name__ == "__main__":
    unittest.main()
