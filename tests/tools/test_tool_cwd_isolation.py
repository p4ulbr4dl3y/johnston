import os
import tempfile
import unittest

from tools.base import resolve_path
from tools.context import ToolContext


class MockTextualApp:
    """Minimal stand-in for the real Textual app (has push_screen)."""

    def __init__(self):
        self.background_tasks = []
        self.current_session_id = None

    def push_screen(self, screen, callback=None):
        raise NotImplementedError


def make_agent(app, cwd=None, is_subagent=False):
    """Build a real BaseAgent wired like a (sub)agent with an optional worktree cwd."""
    from core.base_provider import BaseAgent

    agent = BaseAgent(api_key="", base_url="", model="")
    agent.app = app
    if cwd is not None:
        agent.cwd = cwd
        agent.project_dir = cwd
    agent.is_subagent = is_subagent
    return agent


class TestToolContextCwdIsolation(unittest.TestCase):
    def test_agent_unwrap_to_host_app(self):
        host = MockTextualApp()
        with tempfile.TemporaryDirectory() as base:
            agent = make_agent(host, cwd=base, is_subagent=True)
            ctx = ToolContext(agent)
            self.assertIs(ctx.app, host)
            self.assertTrue(ctx.is_subagent)
            self.assertEqual(ctx.cwd, os.path.realpath(base))

    def test_agent_untrusted_nonexistent_cwd_ignored(self):
        host = MockTextualApp()
        agent = make_agent(host, cwd="/definitely/not/a/real/dir", is_subagent=True)
        ctx = ToolContext(agent)
        self.assertIs(ctx.app, host)
        self.assertTrue(ctx.is_subagent)
        self.assertIsNone(ctx.cwd)

    def test_main_agent_no_isolation(self):
        host = MockTextualApp()
        agent = make_agent(host)
        ctx = ToolContext(agent)
        self.assertIs(ctx.app, host)
        self.assertFalse(ctx.is_subagent)
        self.assertIsNone(ctx.cwd)

    def test_subagent_keeps_cwd(self):
        with tempfile.TemporaryDirectory() as base:
            ctx = ToolContext(None, is_subagent=True, cwd=base)
            self.assertTrue(ctx.is_subagent)
            self.assertEqual(ctx.cwd, os.path.realpath(base))


class TestResolvePathCwd(unittest.TestCase):
    def test_relative_resolved_against_cwd(self):
        with tempfile.TemporaryDirectory() as base:
            resolved = resolve_path("a/b.txt", cwd=base)
            self.assertTrue(os.path.isabs(resolved))
            self.assertTrue(resolved.startswith(os.path.realpath(base)))

    def test_absolute_ignores_cwd(self):
        with tempfile.TemporaryDirectory() as base, tempfile.TemporaryDirectory() as other:
            resolved = resolve_path(os.path.join(other, "x.txt"), cwd=base)
            self.assertTrue(os.path.realpath(resolved).startswith(os.path.realpath(other)))

    def test_empty_path_returns_cwd(self):
        with tempfile.TemporaryDirectory() as base:
            self.assertEqual(resolve_path("", cwd=base), os.path.realpath(base))


class TestShellCwdPropagation(unittest.IsolatedAsyncioTestCase):
    async def test_shell_uses_ctx_cwd_as_process_cwd(self):
        from tools.shell import ShellTool

        tool = ShellTool()
        with tempfile.TemporaryDirectory() as base:
            ctx = ToolContext(None, is_subagent=True, cwd=base)
            res = await tool.execute({"command": "pwd"}, ctx)
            self.assertIn(os.path.realpath(base), res)

    async def test_shell_uses_cwd_from_agent(self):
        from tools.shell import ShellTool

        tool = ShellTool()
        with tempfile.TemporaryDirectory() as base:
            host = MockTextualApp()
            agent = make_agent(host, cwd=base, is_subagent=True)
            res = await tool.execute({"command": "pwd"}, agent)
            self.assertIn(os.path.realpath(base), res)


class TestCreateToolCwd(unittest.IsolatedAsyncioTestCase):
    async def test_create_writes_to_rel_path_under_agent_cwd(self):
        from tools.create import CreateTool

        tool = CreateTool()
        with tempfile.TemporaryDirectory() as base:
            host = MockTextualApp()
            agent = make_agent(host, cwd=base, is_subagent=True)
            res = await tool.execute({"path": "subdir/newfile.txt", "content": "hello"}, agent)
            self.assertNotIn("ERR:", res, res)
            target = os.path.join(base, "subdir", "newfile.txt")
            self.assertTrue(os.path.isfile(target))
            with open(target, encoding="utf-8") as f:
                self.assertEqual(f.read().rstrip(), "hello")


class TestPromptBuilderCwd(unittest.TestCase):
    def test_system_prompt_shows_agent_cwd(self):
        from core.application.generation.prompt_builder import PromptBuilder

        with tempfile.TemporaryDirectory() as base:
            with open(os.path.join(base, "AGENTS.md"), "w", encoding="utf-8") as f:
                f.write("# Worktree rules\nDo work only here.\n")
            builder = PromptBuilder("You are X.", [], model_name="m", cwd=base)
            prompt = builder.build_system_prompt()
            self.assertIn(os.path.realpath(base), prompt)
            self.assertIn("Working Directory", prompt)
            self.assertIn("Worktree rules", prompt)

    def test_system_prompt_loads_project_rules_from_cwd(self):
        """Project rules (.johnston/rules) are read from the agent cwd, not main checkout."""
        from core.application.generation.prompt_builder import PromptBuilder

        with tempfile.TemporaryDirectory() as base:
            rules_dir = os.path.join(base, ".johnston", "rules")
            os.makedirs(rules_dir)
            with open(os.path.join(rules_dir, "pref.md"), "w", encoding="utf-8") as f:
                f.write("---\nname: subagent-pref\n---\nAlways use this subagent rule.\n")
            builder = PromptBuilder("You are X.", [], model_name="m", cwd=base)
            prompt = builder.build_system_prompt()
            self.assertIn("Always use this subagent rule", prompt)
            self.assertIn("subagent-pref", prompt)


class TestGetRulesSnippetCwd(unittest.TestCase):
    def test_get_rules_snippet_respects_cwd(self):
        from core.application.generation.prompt_builder import get_rules_snippet

        with tempfile.TemporaryDirectory() as main, tempfile.TemporaryDirectory() as wt:
            proj_rules = os.path.join(wt, ".johnston", "rules")
            os.makedirs(proj_rules)
            with open(os.path.join(proj_rules, "r.md"), "w", encoding="utf-8") as f:
                f.write("---\nname: wt-rule\n---\nWT-specific rule.\n")
            snippet = get_rules_snippet(role="action", cwd=wt)
            self.assertIn("WT-specific rule", snippet)
            self.assertNotIn("WT-specific rule", get_rules_snippet(role="action", cwd=main))


class TestSubagentBranchContextPersistence(unittest.TestCase):
    """Follow-up subagents must recover their isolated worktree cwd/branch after reload."""

    def test_session_persists_project_dir_and_branch(self):
        import tempfile

        from core.session_manager import AgentSession, SessionStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = SessionStore(project_path=tmpdir)
            sess = store.create_subagent(
                parent_id="sess-main",
                subagent_id="sub-abc",
                role="worker",
                description="desc",
                prompt="prompt",
                project_dir="/tmp/wt/sub-abc",
                branch_name="subagent-sub-abc",
            )
            data = sess.to_dict()
            self.assertEqual(data["project_dir"], "/tmp/wt/sub-abc")
            self.assertEqual(data["branch_name"], "subagent-sub-abc")

            restored = AgentSession.from_dict(data)
            self.assertEqual(restored.project_dir, "/tmp/wt/sub-abc")
            self.assertEqual(restored.branch_name, "subagent-sub-abc")

    def test_from_dict_defaults_empty(self):
        from core.session_manager import AgentSession

        restored = AgentSession.from_dict({"id": "x", "kind": "subagent"})
        self.assertEqual(restored.project_dir, "")
        self.assertEqual(restored.branch_name, "")


if __name__ == "__main__":
    unittest.main()
