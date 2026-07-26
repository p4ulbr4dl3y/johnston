import tempfile
import unittest

from core.config import MAX_CONCURRENT_SUBAGENTS
from core.subagent_tracker import SUBAGENTS_DIR, SubagentTracker
from tools.context import ToolContext
from tools.subagent import SubagentTool


class TestSubagentTool(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        ToolContext._instance = None
        self.old_dir = SUBAGENTS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.tracker = SubagentTracker.get_instance()
        self.tracker.storage_dir = self.temp_dir.name
        self.tracker.sessions.clear()

    async def asyncTearDown(self):
        ToolContext._instance = None
        for sess in list(self.tracker.sessions.values()):
            if sess.async_task and not sess.async_task.done():
                sess.async_task.cancel()
        self.tracker.sessions.clear()
        self.tracker.storage_dir = self.old_dir
        self.temp_dir.cleanup()

    async def test_max_concurrent_subagents_limit(self):
        tool = SubagentTool()

        # Populate tracker with MAX_CONCURRENT_SUBAGENTS running sessions
        for i in range(MAX_CONCURRENT_SUBAGENTS):
            sess = self.tracker.create_session(f"task-{i}", f"Task {i}", "prompt", "general", True)
            sess.status = "running"

        # Attempt to spawn one more
        res = await tool.execute({"prompt": "another task", "description": "Over limit"})
        self.assertIn("Maximum concurrent subagents limit", res)
    async def test_explore_subagent_tool_filtering(self):
        from unittest.mock import MagicMock
        tool = SubagentTool()

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

        tool._ensure_context = lambda app=None: mock_ctx

        await tool.execute({"prompt": "search codebase", "subagent_type": "explore"})

        tool_names = [t.get("function", {}).get("name") for t in mock_agent.tools]
        self.assertIn("read", tool_names)
        self.assertIn("shell", tool_names)
        self.assertNotIn("create", tool_names)
        self.assertNotIn("edit", tool_names)
        self.assertIn("read-only exploration subagent", mock_agent.system_prompt)

    def test_truncate_subagent_result_short(self):
        from tools.subagent import _truncate_subagent_result
        self.assertEqual(_truncate_subagent_result("short result"), "short result")
        self.assertEqual(_truncate_subagent_result(""), "")
        self.assertEqual(_truncate_subagent_result(None), "")

    def test_truncate_subagent_result_long(self):
        from tools.subagent import MAX_SUBAGENT_RESULT_CHARS, _truncate_subagent_result
        long_text = "x" * (MAX_SUBAGENT_RESULT_CHARS + 500)
        result = _truncate_subagent_result(long_text)
        # Clipped and annotated with a pointer to the full session log
        self.assertLess(len(result), len(long_text))
        self.assertTrue(result.startswith("x" * MAX_SUBAGENT_RESULT_CHARS))
        self.assertIn("truncated", result)
        self.assertIn("manage_subagent", result)


if __name__ == "__main__":
    unittest.main()
