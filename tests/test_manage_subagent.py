import unittest

from core.subagent_tracker import SubagentTracker
from tools.manage_subagent import ManageSubagentTool


class TestManageSubagentTool(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        from tools.context import ToolContext
        ToolContext._instance = None
        self.tracker = SubagentTracker.get_instance()
        self.tracker.sessions.clear()

    async def asyncTearDown(self):
        from tools.context import ToolContext
        ToolContext._instance = None
        for sess in list(self.tracker.sessions.values()):
            if sess.async_task and not sess.async_task.done():
                sess.async_task.cancel()
        self.tracker.sessions.clear()

    async def test_list_action(self):
        tool = ManageSubagentTool()
        res_empty = await tool.execute({"action": "list"})
        self.assertIn("No subagent sessions registered", res_empty)

        self.tracker.create_session("sub-1", "Search files", "find python files", "explore", False)
        res_list = await tool.execute({"action": "list"})
        self.assertIn("sub-1", res_list)
        self.assertIn("Search files", res_list)

    async def test_status_action(self):
        tool = ManageSubagentTool()
        sess = self.tracker.create_session("sub-2", "Refactor module", "clean up code", "general", True)
        sess.add_event({"type": "user", "text": "clean up code"})
        sess.add_event({"type": "bot_text", "text": "Done cleaning."})

        res_status = await tool.execute({"action": "status", "task_id": "sub-2"})
        self.assertIn("sub-2", res_status)
        self.assertIn("Refactor module", res_status)
        self.assertIn("[User]: clean up code", res_status)

    async def test_kill_action(self):
        tool = ManageSubagentTool()
        sess = self.tracker.create_session("sub-3", "Long running task", "do heavy work", "general", True)

        res_kill = await tool.execute({"action": "kill", "task_id": "sub-3"})
        self.assertIn("has been terminated", res_kill)
        self.assertEqual(sess.status, "cancelled")

        # Second kill on finished task
        res_kill_again = await tool.execute({"action": "kill", "task_id": "sub-3"})
        self.assertIn("already in state 'cancelled'", res_kill_again)


if __name__ == "__main__":
    unittest.main()
