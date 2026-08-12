import tempfile
import unittest

from core.defaults.config import MAX_CONCURRENT_SUBAGENTS
from core.session_manager import SessionStore
from tools.invoke_subagent import MAX_SUBAGENT_RESULT_CHARS, InvokeSubagentTool, _truncate_subagent_result


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
        mock_ctx.app = mock_app
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
        res = await tool.execute({"prompt": "another task", "description": "Over limit"})
        self.assertIn("ERR: limit: 5 concurrent max", res)

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
        mock_ctx.app = mock_app
        mock_ctx.create_agent.return_value = mock_agent
        mock_ctx.background_tasks = []
        mock_app.sm = self.store
        mock_app.current_session_id = "sess-main"

        tool._ensure_context = lambda app=None: mock_ctx

        await tool.execute({"prompt": "search codebase", "subagent_type": "explorer"})

        tool_names = [t.get("function", {}).get("name") for t in mock_agent.tools]
        self.assertIn("read", tool_names)
        self.assertIn("shell", tool_names)
        self.assertNotIn("create", tool_names)
        self.assertNotIn("edit", tool_names)
        self.assertIn("## Execution Mode: EXPLORER", mock_agent.system_prompt)

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
        mock_ctx.app = mock_app
        mock_ctx.create_agent.return_value = mock_agent
        mock_ctx.background_tasks = []
        mock_app.sm = self.store
        mock_app.current_session_id = "sess-main"

        tool._ensure_context = lambda app=None: mock_ctx

        await tool.execute({"prompt": "run task", "subagent_type": "worker"})

        self.assertTrue(mock_agent.is_subagent)
        tool_names = [t.get("function", {}).get("name") for t in mock_agent.tools]
        self.assertIn("read", tool_names)
        self.assertIn("shell", tool_names)
        self.assertNotIn("invoke_subagent", tool_names)
        self.assertNotIn("manage_shell", tool_names)

    def test_truncate_subagent_result_short(self):
        self.assertEqual(_truncate_subagent_result("short result"), "short result")
        self.assertEqual(_truncate_subagent_result(""), "")
        self.assertEqual(_truncate_subagent_result(None), "")

    def test_truncate_subagent_result_long(self):
        long_text = "x" * (MAX_SUBAGENT_RESULT_CHARS + 500)
        result = _truncate_subagent_result(long_text)
        # Clipped and annotated with a pointer to the full session log
        self.assertLess(len(result), len(long_text))
        self.assertTrue(result.startswith("x" * MAX_SUBAGENT_RESULT_CHARS))
        self.assertIn("truncated", result)
        self.assertIn("Use `read` tool", result)


if __name__ == "__main__":
    unittest.main()
