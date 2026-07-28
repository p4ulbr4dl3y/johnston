import unittest
from unittest.mock import MagicMock

from core.subagent_tracker import SubagentTracker
from tools.manage_subagent import ManageSubagentTool


class TestManageSubagentTool(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        import tempfile

        from core.subagent_tracker import SUBAGENTS_DIR
        self.old_dir = SUBAGENTS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.tracker = SubagentTracker.get_instance()
        self.tracker.storage_dir = self.temp_dir.name
        self.tracker.sessions.clear()

    async def asyncTearDown(self):
        for sess in list(self.tracker.sessions.values()):
            if sess.async_task and not sess.async_task.done():
                sess.async_task.cancel()
        self.tracker.sessions.clear()
        self.tracker.storage_dir = self.old_dir
        self.temp_dir.cleanup()

    async def test_list_action(self):
        tool = ManageSubagentTool()
        res_empty = await tool.execute({"action": "list"})
        self.assertIn("Available Subagent Definitions", res_empty)

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
        self.assertIn("Full Log File:", res_status)
        self.assertIn("sub-2.json", res_status)

    async def test_kill_action(self):
        tool = ManageSubagentTool()
        sess = self.tracker.create_session("sub-3", "Long running task", "do heavy work", "general", True)

        res_kill = await tool.execute({"action": "kill", "task_id": "sub-3"})
        self.assertIn("has been terminated", res_kill)
        self.assertEqual(sess.status, "cancelled")

        # Second kill on finished task
        res_kill_again = await tool.execute({"action": "kill", "task_id": "sub-3"})
        self.assertIn("already in state 'cancelled'", res_kill_again)

    def test_subagent_session_data_agent_history_deserialization(self):
        from core.subagent_tracker import SubagentSessionData
        data = {
            "task_id": "sub-test",
            "description": "test desc",
            "prompt": "test prompt",
            "subagent_type": "general",
            "background": False,
            "status": "completed",
            "agent_history": [{"role": "user", "content": "Prior prompt"}, {"role": "assistant", "content": "Prior response"}]
        }
        sess = SubagentSessionData.from_dict(data)
        self.assertEqual(len(sess.agent_history), 2)
        self.assertEqual(sess.to_dict()["agent_history"], data["agent_history"])


class TestManageSubagentSendMessage(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        import tempfile

        from core.subagent_tracker import SUBAGENTS_DIR, SubagentTracker
        self.old_dir = SUBAGENTS_DIR
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.tracker = SubagentTracker.get_instance()
        self.tracker.storage_dir = self.temp_dir.name
        self.tracker.sessions.clear()

    async def asyncTearDown(self):
        for sess in list(self.tracker.sessions.values()):
            if sess.async_task and not sess.async_task.done():
                sess.async_task.cancel()
        self.tracker.sessions.clear()
        self.tracker.storage_dir = self.old_dir

    async def test_send_message_no_message(self):
        tool = ManageSubagentTool()
        self.tracker.create_session("sub-sm1", "Task", "prompt", "general", False)
        res = await tool.execute({"action": "send_message", "task_id": "sub-sm1"}, app=MagicMock())
        self.assertIn("'message' parameter is required", res)

    async def test_send_message_no_task_id(self):
        tool = ManageSubagentTool()
        res = await tool.execute({"action": "send_message", "message": "hi"})
        self.assertIn("'task_id' parameter is required", res)

    async def test_send_message_task_not_found(self):
        tool = ManageSubagentTool()
        res = await tool.execute({"action": "send_message", "task_id": "ghost", "message": "hi"})
        self.assertIn("not found", res)

    async def test_send_message_no_agent_available(self):
        tool = ManageSubagentTool()
        self.tracker.create_session("sub-sm2", "Task", "prompt", "general", False)
        mock_app = MagicMock()
        mock_app.current_session_id = None
        mock_app.pm = MagicMock()
        mock_app.pm.create_active_agent.return_value = None
        res = await tool.execute({"action": "send_message", "task_id": "sub-sm2", "message": "hi"}, app=mock_app)
        self.assertIn("No active agent instance", res)

    async def test_send_message_sync_success(self):
        tool = ManageSubagentTool()
        sess = self.tracker.create_session("sub-sm3", "Task", "prompt", "general", False)

        class MockSubagent:
            def __init__(self):
                self.app = None
                self.history = []
                self.tokens_input = 0
                self.tokens_output = 0
                self.total_tokens = 0
                self.cost_usd = 0.0
                self._merged_tokens_input = 0
                self._merged_tokens_output = 0
                self._merged_total_tokens = 0
                self._merged_cost_usd = 0.0

            async def stream_steps(self, message):
                yield ("bot_text", "Subagent reply text")

        mock_agent = MockSubagent()
        mock_app = MagicMock()
        mock_app.current_session_id = None
        mock_app.project_dir = None
        mock_app.agent = None
        mock_app.pm = MagicMock()
        mock_app.pm.create_active_agent.return_value = mock_agent
        res = await tool.execute({"action": "send_message", "task_id": "sub-sm3", "message": "hello"}, app=mock_app)
        self.assertIn("<task_result>", res)
        self.assertIn("Subagent reply text", res)
        self.assertIsNotNone(sess.agent)

    async def test_unknown_action(self):
        tool = ManageSubagentTool()
        self.tracker.create_session("sub-unk", "Task", "prompt", "general", False)
        res = await tool.execute({"action": "bogus", "task_id": "sub-unk"})
        self.assertIn("Unknown action", res)
        self.assertIn("bogus", res)

    async def test_send_message_background(self):
        tool = ManageSubagentTool()
        self.tracker.create_session("sub-bg", "Task", "prompt", "general", True)

        class MockSubagent:
            def __init__(self):
                self.app = None
                self.history = []
                self.tokens_input = 0
                self.tokens_output = 0
                self.total_tokens = 0
                self.cost_usd = 0.0
                self._merged_tokens_input = 0
                self._merged_tokens_output = 0
                self._merged_total_tokens = 0
                self._merged_cost_usd = 0.0

            async def stream_steps(self, message):
                yield ("bot_text", "Background response")

        mock_agent = MockSubagent()
        mock_app = MagicMock()
        mock_app.current_session_id = None
        mock_app.project_dir = None
        mock_app.agent = None
        mock_app.pm = MagicMock()
        mock_app.pm.create_active_agent.return_value = mock_agent

        res = await tool.execute({"action": "send_message", "task_id": "sub-bg", "message": "hello bg"}, app=mock_app)
        self.assertIn("Message sent to background subagent sub-bg", res)


    async def test_status_and_kill_missing_task_id(self):
        tool = ManageSubagentTool()
        res_st = await tool.execute({"action": "status"})
        self.assertIn("'task_id' parameter is required", res_st)

        res_kl = await tool.execute({"action": "kill"})
        self.assertIn("'task_id' parameter is required", res_kl)


if __name__ == "__main__":
    unittest.main()

