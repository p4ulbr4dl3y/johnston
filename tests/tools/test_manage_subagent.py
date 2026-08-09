import tempfile
import unittest
from unittest.mock import MagicMock

from core.session_manager import AgentSession, SessionStore
from tools.manage_subagent import ManageSubagentTool


def _make_store(tmpdir: str) -> SessionStore:
    store = SessionStore(project_path=tmpdir)
    return store


class TestManageSubagentTool(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = _make_store(self.temp_dir.name)
        self.store._sessions.clear()
        # Track old instance to avoid cross-test pollution
        self._old_instance = SessionStore._instance
        SessionStore._instance = self.store

    async def asyncTearDown(self):
        SessionStore._instance = self._old_instance

    def _mk_subagent(self, sid: str, desc: str, prompt: str, role: str = "worker", status: str = "running") -> AgentSession:
        return self.store.create_subagent(
            parent_id="sess-main",
            subagent_id=sid,
            role=role,
            description=desc,
            prompt=prompt,
            status=status,
        )

    async def test_list_action(self):
        tool = ManageSubagentTool()
        res_empty = await tool.execute({"action": "list"})
        self.assertIn("Available Subagent Roles", res_empty)

        self._mk_subagent("sub-1", "Search files", "find python files", role="explore")
        res_list = await tool.execute({"action": "list"})
        self.assertIn("sub-1", res_list)
        self.assertIn("Search files", res_list)

    async def test_status_action(self):
        tool = ManageSubagentTool()
        sess = self._mk_subagent("sub-2", "Refactor module", "clean up code", role="worker")
        sess.add_event({"type": "user", "text": "clean up code"})
        sess.add_event({"type": "bot_text", "text": "Done cleaning."})

        res_status = await tool.execute({"action": "status", "task_id": "sub-2"})
        self.assertIn("sub-2", res_status)
        self.assertIn("Refactor module", res_status)
        self.assertIn("[User]: clean up code", res_status)
        # No log-file path / snippet: status is metadata-only now
        self.assertNotIn("Log File:", res_status)
        self.assertNotIn(".log", res_status)
        self.assertNotIn("Final Response Snippet", res_status)

    async def test_kill_action(self):
        tool = ManageSubagentTool()
        sess = self._mk_subagent("sub-3", "Long running task", "do heavy work", role="worker")

        res_kill = await tool.execute({"action": "kill", "task_id": "sub-3"})
        self.assertIn("OK: sub-3 terminated", res_kill)
        self.assertEqual(sess.status, "cancelled")

        # Second kill on finished task
        res_kill_again = await tool.execute({"action": "kill", "task_id": "sub-3"})
        self.assertIn("OK: sub-3 already in 'cancelled'", res_kill_again)

    def test_agent_session_deserialization(self):
        data = {
            "id": "sub-test",
            "kind": "subagent",
            "parent_id": "sess-main",
            "role": "worker",
            "status": "completed",
            "description": "test desc",
            "prompt": "test prompt",
            "agent_history": [{"role": "user", "content": "Prior prompt"}, {"role": "assistant", "content": "Prior response"}]
        }
        sess = AgentSession.from_dict(data)
        self.assertEqual(len(sess.agent_history), 2)
        self.assertEqual(sess.to_dict()["agent_history"], data["agent_history"])


class TestManageSubagentSendMessage(unittest.IsolatedAsyncioTestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = _make_store(self.temp_dir.name)
        self._old_instance = SessionStore._instance
        SessionStore._instance = self.store

    async def asyncTearDown(self):
        SessionStore._instance = self._old_instance

    def _mk_subagent(self, sid: str, desc: str = "Task", prompt: str = "prompt", role: str = "worker", status: str = "running", background: bool = False) -> AgentSession:
        return self.store.create_subagent(
            parent_id="sess-main",
            subagent_id=sid,
            role=role,
            description=desc,
            prompt=prompt,
            status=status,
            background=background,
        )

    async def test_send_message_no_message(self):
        tool = ManageSubagentTool()
        self._mk_subagent("sub-sm1")
        res = await tool.execute({"action": "send_message", "task_id": "sub-sm1"}, app=MagicMock())
        self.assertIn("ERR: 'message' required", res)

    async def test_send_message_no_task_id(self):
        tool = ManageSubagentTool()
        res = await tool.execute({"action": "send_message", "message": "hi"})
        self.assertIn("ERR: 'task_id' required for 'send_message'", res)

    async def test_send_message_task_not_found(self):
        tool = ManageSubagentTool()
        res = await tool.execute({"action": "send_message", "task_id": "ghost", "message": "hi"})
        self.assertIn("ERR: session 'ghost' not found", res)

    async def test_send_message_no_agent_available(self):
        tool = ManageSubagentTool()
        self._mk_subagent("sub-sm2")
        mock_app = MagicMock()
        mock_app.current_session_id = None
        mock_app.sm = self.store
        mock_app.pm = MagicMock()
        mock_app.pm.create_active_agent.return_value = None
        res = await tool.execute({"action": "send_message", "task_id": "sub-sm2", "message": "hi"}, app=mock_app)
        self.assertIn("ERR: no active agent for sub-sm2", res)

    async def test_send_message_sync_success(self):
        tool = ManageSubagentTool()
        sess = self._mk_subagent("sub-sm3")

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
        mock_app.sm = self.store
        mock_app.pm = MagicMock()
        mock_app.pm.create_active_agent.return_value = mock_agent
        res = await tool.execute({"action": "send_message", "task_id": "sub-sm3", "message": "hello"}, app=mock_app)
        self.assertIn("<task_result>", res)
        self.assertIn("Subagent reply text", res)
        self.assertIsNotNone(sess.agent)
        self.assertEqual(sess.status, "completed")

    async def test_unknown_action(self):
        tool = ManageSubagentTool()
        self._mk_subagent("sub-unk")
        res = await tool.execute({"action": "bogus", "task_id": "sub-unk"})
        self.assertIn("ERR: unknown action 'bogus'", res)
        self.assertIn("bogus", res)

    async def test_send_message_background(self):
        tool = ManageSubagentTool()
        self._mk_subagent("sub-bg", background=True)

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
        mock_app.sm = self.store
        mock_app.pm = MagicMock()
        mock_app.pm.create_active_agent.return_value = mock_agent

        res = await tool.execute({"action": "send_message", "task_id": "sub-bg", "message": "hello bg"}, app=mock_app)
        self.assertIn("OK: message sent to sub-bg", res)

    async def test_status_and_kill_missing_task_id(self):
        tool = ManageSubagentTool()
        res_st = await tool.execute({"action": "status"})
        self.assertIn("ERR: 'task_id' required for 'status'", res_st)

        res_kl = await tool.execute({"action": "kill"})
        self.assertIn("ERR: 'task_id' required for 'kill'", res_kl)


if __name__ == "__main__":
    unittest.main()
