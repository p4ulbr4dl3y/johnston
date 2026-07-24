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
        self.assertIn(str(MAX_CONCURRENT_SUBAGENTS), res)


if __name__ == "__main__":
    unittest.main()
