import tempfile
import unittest

from core.domain.defaults.config import MAX_CONCURRENT_SUBAGENTS
from core.infrastructure.storage.session_store import SessionStore
from core.infrastructure.tasks.output import MAX_SUBAGENT_RESULT_CHARS, truncate_subagent_result
from tools.invoke_subagent import InvokeSubagentTool


class TestInvokeSubagentTool(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = SessionStore(project_path=self.temp_dir.name)
        self._old_instance = SessionStore._instance
        SessionStore._instance = self.store

    async def asyncTearDown(self):
        SessionStore._instance = self._old_instance
        self.temp_dir.cleanup()

    async def test_max_concurrent_subagents_limit(self):
        from unittest.mock import MagicMock

        tool = InvokeSubagentTool()
        mock_app = MagicMock()
        mock_app.current_session_id = "sess-main"
        mock_app.sm = self.store
        mock_ctx = MagicMock()
        mock_ctx.host = mock_app
        mock_ctx.background_tasks = []
        tool._ensure_context = lambda app=None: mock_ctx

        # Populate store with MAX_CONCURRENT_SUBAGENTS running sessions
        for i in range(MAX_CONCURRENT_SUBAGENTS):
            self.store.create_subagent(
                parent_id="sess-main",
                subagent_id=f"task-{i}",
                role="worker",
                description=f"Task {i}",
                prompt="prompt",
                status="running",
            )

        # Attempt to spawn one more
        res = str(await tool.execute({"prompt": "another task", "title": "Over limit", "branch": "main"}))
        self.assertIn("ERR: limit: 5 concurrent max", res)

    async def test_custom_max_concurrent_subagents_limit(self):
        from unittest.mock import MagicMock, patch

        tool = InvokeSubagentTool()
        mock_app = MagicMock()
        mock_app.current_session_id = "sess-main"
        mock_app.sm = self.store
        mock_ctx = MagicMock()
        mock_ctx.host = mock_app
        mock_ctx.background_tasks = []
        tool._ensure_context = lambda app=None: mock_ctx

        # Populate store with 2 running sessions
        for i in range(2):
            self.store.create_subagent(
                parent_id="sess-main",
                subagent_id=f"task-custom-{i}",
                role="worker",
                description=f"Task {i}",
                prompt="prompt",
                status="running",
            )

        # With limit=2, spawning should fail with "2 concurrent max"
        with patch("tools.invoke_subagent.load_max_concurrent_subagents", return_value=2):
            res = str(await tool.execute({"prompt": "another task", "title": "Over limit", "branch": "main"}))
            self.assertIn("ERR: limit: 2 concurrent max", res)

    async def test_explore_subagent_tool_filtering(self):
        from unittest.mock import MagicMock

        tool = InvokeSubagentTool()

        # Mock app context and agent
        mock_app = MagicMock()
        mock_agent = MagicMock()
        mock_agent.tools = [
            {"function": {"name": "read"}},
            {"function": {"name": "create"}},
            {"function": {"name": "edit"}},
            {"function": {"name": "shell"}},
        ]
        mock_agent.system_prompt = "Base prompt"
        mock_agent.stream_steps.return_value = (x for x in [])

        mock_ctx = MagicMock()
        mock_ctx.host = mock_app
        mock_ctx.create_agent.return_value = mock_agent
        mock_ctx.background_tasks = []
        mock_app.sm = self.store
        mock_app.current_session_id = "sess-main"

        tool._ensure_context = lambda app=None: mock_ctx

        await tool.execute({"prompt": "search codebase", "type": "explorer", "branch": "main"})

        tool_names = [t.get("function", {}).get("name") for t in mock_agent.tools]
        self.assertIn("read", tool_names)
        self.assertIn("shell", tool_names)
        self.assertNotIn("create", tool_names)
        self.assertNotIn("edit", tool_names)
        self.assertIn('<role name="explorer"', mock_agent.system_prompt)

    async def test_subagent_tool_exclusion_of_manage_shell_and_recursion_guards(self):
        from unittest.mock import MagicMock

        tool = InvokeSubagentTool()

        mock_app = MagicMock()
        mock_agent = MagicMock()
        mock_agent.tools = [
            {"function": {"name": "read"}},
            {"function": {"name": "shell"}},
            {"function": {"name": "invoke_subagent"}},
            {"function": {"name": "manage_shell"}},
        ]
        mock_agent.system_prompt = "Base prompt"
        mock_agent.stream_steps.return_value = (x for x in [])

        mock_ctx = MagicMock()
        mock_ctx.host = mock_app
        mock_ctx.create_agent.return_value = mock_agent
        mock_ctx.background_tasks = []
        mock_app.sm = self.store
        mock_app.current_session_id = "sess-main"

        tool._ensure_context = lambda app=None: mock_ctx

        await tool.execute({"prompt": "run task", "type": "worker", "branch": "main"})

        self.assertTrue(mock_agent.is_subagent)
        tool_names = [t.get("function", {}).get("name") for t in mock_agent.tools]
        self.assertIn("read", tool_names)
        self.assertIn("shell", tool_names)
        self.assertNotIn("invoke_subagent", tool_names)
        self.assertNotIn("manage_shell", tool_names)

    async def test_invoke_subagent_without_branch_succeeds(self):
        from unittest.mock import MagicMock

        tool = InvokeSubagentTool()

        mock_app = MagicMock()
        mock_agent = MagicMock()
        mock_agent.tools = [{"function": {"name": "read"}}]
        mock_agent.system_prompt = "Base prompt"
        mock_agent.stream_steps.return_value = (x for x in [])

        mock_ctx = MagicMock()
        mock_ctx.host = mock_app
        mock_ctx.create_agent.return_value = mock_agent
        mock_ctx.background_tasks = []
        mock_ctx.project_dir = self.temp_dir.name
        mock_app.sm = self.store
        mock_app.current_session_id = "sess-main"

        tool._ensure_context = lambda app=None: mock_ctx

        res = await tool.execute({"prompt": "inspect repo", "title": "inspect"})
        self.assertEqual(res.status.value, "running")
        sessions = self.store.list(kind="subagent")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].branch_name, "")
        self.assertEqual(sessions[0].project_dir, "")

    async def test_invoke_subagent_with_branch_non_git_sets_empty_branch(self):
        from unittest.mock import MagicMock

        tool = InvokeSubagentTool()

        mock_app = MagicMock()
        mock_agent = MagicMock()
        mock_agent.tools = [{"function": {"name": "read"}}]
        mock_agent.system_prompt = "Base prompt"
        mock_agent.stream_steps.return_value = (x for x in [])

        mock_ctx = MagicMock()
        mock_ctx.host = mock_app
        mock_ctx.create_agent.return_value = mock_agent
        mock_ctx.background_tasks = []
        mock_ctx.project_dir = self.temp_dir.name
        mock_app.sm = self.store
        mock_app.current_session_id = "sess-main"

        tool._ensure_context = lambda app=None: mock_ctx

        res = await tool.execute({"prompt": "inspect repo", "description": "inspect", "branch": "feat-x"})
        self.assertEqual(res.status.value, "running")
        sessions = self.store.list(kind="subagent")
        self.assertEqual(len(sessions), 1)
        self.assertEqual(sessions[0].branch_name, "")
        self.assertEqual(sessions[0].project_dir, "")

    def test_truncate_subagent_result_short(self):
        self.assertEqual(truncate_subagent_result("short result"), "short result")
        self.assertEqual(truncate_subagent_result(""), "")
        self.assertEqual(truncate_subagent_result(None), "")

    def test_truncate_subagent_result_long(self):
        long_text = "x" * (MAX_SUBAGENT_RESULT_CHARS + 500)
        result = truncate_subagent_result(long_text)
        # Clipped and annotated with a pointer to the full session log
        self.assertLess(len(result), len(long_text))
        self.assertTrue(result.startswith("x" * MAX_SUBAGENT_RESULT_CHARS))
        self.assertIn("Truncated:", result)
        self.assertIn("Next: read(path=", result)

    def test_truncate_subagent_result_with_session_id(self):
        long_text = "x" * (MAX_SUBAGENT_RESULT_CHARS + 500)
        result = truncate_subagent_result(long_text, session_id="subagent-3a1f9b")
        self.assertIn("subagent-3a1f9b.md", result)


if __name__ == "__main__":
    unittest.main()
