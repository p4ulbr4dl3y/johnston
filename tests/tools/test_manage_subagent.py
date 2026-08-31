import tempfile
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from core.domain.entities.session import AgentSession
from core.infrastructure.storage.session_store import SessionStore
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

    def _mk_subagent(
        self, sid: str, desc: str, prompt: str, role: str = "worker", status: str = "running"
    ) -> AgentSession:
        return self.store.create_subagent(
            parent_id="sess-main",
            subagent_id=sid,
            role=role,
            title=desc,
            prompt=prompt,
            status=status,
        )

    async def test_list_action(self):
        tool = ManageSubagentTool()
        res_empty = await tool.execute({"action": "list"})
        self.assertEqual(res_empty.content, "[subagents 0]")
        self.assertIn("No subagent sessions found for current session", res_empty.display)

        self._mk_subagent("sub-1", "Search files", "find python files", role="explorer")
        self._mk_subagent("sub-2", "Run tests", "run pytest", role="worker", status="completed")
        self._mk_subagent("sub-3", "", "fallback prompt text", role="tester", status="error")
        self._mk_subagent("sub-4", "Cancelled task", "", role="coder", status="cancelled")

        res = await tool.execute({"action": "list"})
        self.assertIn("[subagents 4 | id|status|role|title]", res.content)
        self.assertIn("sub-1|running|explorer|Search files", res.content)
        self.assertIn("sub-2|completed|worker|Run tests", res.content)
        self.assertIn("sub-3|error|tester|fallback prompt text", res.content)
        self.assertIn("sub-4|cancelled|coder|Cancelled task", res.content)
        self.assertIn("Explorer", res.display)
        self.assertIn("RUNNING", res.display)
        self.assertIn("COMPLETED", res.display)
        self.assertIn("ERROR", res.display)
        self.assertIn("CANCELLED", res.display)

    async def test_kill_action(self):
        tool = ManageSubagentTool()
        sess = self._mk_subagent("sub-kill", "Kill task", "prompt", status="running")
        mock_task = MagicMock()
        mock_task.done.return_value = False
        sess.async_task = mock_task

        res = await tool.execute({"action": "kill", "session_id": "sub-kill"})
        self.assertEqual(res.content, "[killed sub-kill]")
        self.assertEqual(sess.status, "cancelled")
        mock_task.cancel.assert_called_once()

    def test_agent_session_deserialization(self):
        data = {
            "id": "sub-test",
            "kind": "subagent",
            "parent_id": "sess-main",
            "role": "worker",
            "status": "completed",
            "title": "test desc",
            "prompt": "test prompt",
            "agent_history": [
                {"role": "user", "content": "Prior prompt"},
                {"role": "assistant", "content": "Prior response"},
            ],
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

    def _mk_subagent(
        self,
        sid: str,
        desc: str = "desc",
        prompt: str = "prompt",
        role: str = "worker",
        status: str = "running",
        background: bool = False,
    ) -> AgentSession:
        return self.store.create_subagent(
            parent_id="sess-main",
            subagent_id=sid,
            role=role,
            title=desc,
            prompt=prompt,
            status=status,
            background=background,
        )

    async def test_send_message_no_message(self):
        tool = ManageSubagentTool()
        self._mk_subagent("sub-sm1")
        res = str(await tool.execute({"action": "send_message", "session_id": "sub-sm1"}, ctx=MagicMock()))
        self.assertIn("ERR: params 'message': required", res)

    async def test_send_message_no_session_id(self):
        tool = ManageSubagentTool()
        res = str(await tool.execute({"action": "send_message", "message": "hi"}))
        self.assertIn("ERR: params 'session_id': required for 'send_message'", res)

    async def test_send_message_task_not_found(self):
        tool = ManageSubagentTool()
        res = str(await tool.execute({"action": "send_message", "session_id": "ghost", "message": "hi"}))
        self.assertIn("ERR: notfound 'ghost'", res)

    async def test_send_message_no_agent_available(self):
        tool = ManageSubagentTool()
        self._mk_subagent("sub-sm2")
        mock_app = MagicMock()
        mock_app.current_session_id = None
        mock_app.sm = self.store
        mock_app.pm = MagicMock()
        mock_app.pm.create_active_agent.return_value = None
        res = str(await tool.execute({"action": "send_message", "session_id": "sub-sm2", "message": "hi"}, ctx=mock_app))
        self.assertIn("ERR: context 'sub-sm2': no active agent", res)

    async def test_send_message_sync_success(self):
        tool = ManageSubagentTool()
        sess = self._mk_subagent("sub-sm3", role="worker")

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
                self.tools = [
                    {"function": {"name": "read"}},
                    {"function": {"name": "invoke_subagent"}},
                    {"function": {"name": "manage_shell"}},
                    {"function": {"name": "ask_user"}},
                    {"function": {"name": "shell"}},
                ]
                self.role = ""
                self.system_prompt = ""
                self.allow_task = True
                self.model = ""

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
        res = str(await tool.execute({"action": "send_message", "session_id": "sub-sm3", "message": "hello"}, ctx=mock_app))
        self.assertIn("message sent to sub-sm3", res)
        self.assertIsNotNone(sess.agent)
        self.assertEqual(sess.status, "running")
        self.assertIsNotNone(sess.async_task)
        # The message is queued and pulled from pending_messages for the stream.
        self.assertEqual(len(sess.pending_messages), 0)

    async def test_unknown_action(self):
        tool = ManageSubagentTool()
        self._mk_subagent("sub-unk")
        res = str(await tool.execute({"action": "bogus", "session_id": "sub-unk"}))
        self.assertIn("ERR: action 'bogus'", res)
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

        res = str(await tool.execute(
            {"action": "send_message", "session_id": "sub-bg", "message": "hello bg"}, ctx=mock_app
        ))
        self.assertIn("message sent to sub-bg", res)

    async def test_kill_missing_session_id(self):
        tool = ManageSubagentTool()

        res_kl = str(await tool.execute({"action": "kill"}))
        self.assertIn("ERR: params 'session_id': required for 'kill'", res_kl)

    async def test_send_message_queued_when_busy(self):
        tool = ManageSubagentTool()
        sess = self._mk_subagent("sub-busy", role="worker")

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
                yield ("bot_text", "In progress")

        mock_agent = MockSubagent()
        sess.agent = mock_agent

        not_done = MagicMock()
        not_done.done.return_value = False
        sess.async_task = not_done

        mock_app = MagicMock()
        mock_app.current_session_id = None
        mock_app.project_dir = None
        mock_app.agent = None
        mock_app.sm = self.store
        mock_app.pm = MagicMock()

        res = str(await tool.execute(
            {"action": "send_message", "session_id": "sub-busy", "message": "again"}, ctx=mock_app
        ))
        self.assertIn("[queued | id sub-busy]", res)
        self.assertEqual(sess.pending_messages, ["again"])

    async def test_send_message_setup_error_handled(self):
        tool = ManageSubagentTool()
        sess = self._mk_subagent("sub-setup", role="worker")

        mock_app = MagicMock()
        mock_app.current_session_id = None
        mock_app.project_dir = None
        mock_app.agent = None
        mock_app.sm = self.store
        mock_app.pm = MagicMock()
        mock_app.pm.create_active_agent.side_effect = RuntimeError("boom setup")

        res = str(await tool.execute(
            {"action": "send_message", "session_id": "sub-setup", "message": "hi"}, ctx=mock_app
        ))
        self.assertIn("ERR: subagent_setup 'sub-setup': boom setup", res)
        self.assertEqual(sess.status, "error")

    async def test_send_message_with_done_task_starts(self):
        tool = ManageSubagentTool()
        sess = self._mk_subagent("sub-done", role="worker")

        mock_app = MagicMock()
        mock_app.current_session_id = None
        mock_app.project_dir = None
        mock_app.agent = None
        mock_app.sm = self.store
        mock_app.pm = MagicMock()
        mock_app.pm.create_active_agent.return_value = None

        done_task = MagicMock()
        done_task.done.return_value = True
        sess.async_task = done_task

        res = str(await tool.execute(
            {"action": "send_message", "session_id": "sub-done", "message": "hi"}, ctx=mock_app
        ))
        self.assertIn("ERR: context 'sub-done': no active agent", res)


class TestManageSubagentSendMessageRunning(unittest.IsolatedAsyncioTestCase):
    """Regression: a successful send_message must flip the invoke_subagent widget
    back to running; on error it must not."""

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)
        self.store = _make_store(self.temp_dir.name)
        self._old_instance = SessionStore._instance
        SessionStore._instance = self.store

    async def asyncTearDown(self):
        SessionStore._instance = self._old_instance

    def _mk_subagent(self, sid, role="worker", status="running"):
        return self.store.create_subagent(
            parent_id="sess-main",
            subagent_id=sid,
            role=role,
            title="Task",
            prompt="prompt",
            status=status,
        )

    def _app_with_widget(self, sess):
        """Build a mock app whose _subagent_tools registry maps sid -> spy widget."""
        spy = MagicMock()
        spy.mark_running = MagicMock()
        spy.set_result = MagicMock()
        app = MagicMock()
        app._subagent_tools = {sess.id: spy}
        app.current_session_id = None
        app.project_dir = None
        app.agent = None
        app.sm = self.store
        app.pm = MagicMock()
        return app, spy

    async def test_send_message_sync_marks_widget_running(self):
        sess = self._mk_subagent("sub-run")
        app, spy = self._app_with_widget(sess)

        class MockSubagent:
            async def stream_steps(self, message):
                yield ("bot_text", "reply")

        app.pm.create_active_agent.return_value = MockSubagent()

        tool = ManageSubagentTool()
        res = str(await tool.execute({"action": "send_message", "session_id": "sub-run", "message": "hi"}, ctx=app))
        self.assertIn("message sent to sub-run", res)
        spy.mark_running.assert_called_once()
        self.assertIn("sub-run", spy.mark_running.call_args.kwargs.get("text", ""))

    async def test_send_message_queued_marks_widget_running(self):
        sess = self._mk_subagent("sub-queue")
        app, spy = self._app_with_widget(sess)
        not_done = MagicMock()
        not_done.done.return_value = False
        sess.async_task = not_done

        tool = ManageSubagentTool()
        res = str(await tool.execute(
            {"action": "send_message", "session_id": "sub-queue", "message": "again"}, ctx=app
        ))
        self.assertIn("[queued | id sub-queue]", res)
        spy.mark_running.assert_called_once()
        self.assertIn("sub-queue", spy.mark_running.call_args.kwargs.get("text", ""))

    async def test_send_message_error_does_not_mark_running(self):
        sess = self._mk_subagent("sub-err")
        app, spy = self._app_with_widget(sess)
        app.pm.create_active_agent.side_effect = RuntimeError("boom")

        tool = ManageSubagentTool()
        res = str(await tool.execute({"action": "send_message", "session_id": "sub-err", "message": "hi"}, ctx=app))
        self.assertIn("ERR: subagent_setup", res)
        spy.mark_running.assert_not_called()

    async def test_send_message_no_widget_is_noop(self):
        sess = self._mk_subagent("sub-noreg")
        app, _ = self._app_with_widget(sess)
        del app._subagent_tools

        class MockSubagent:
            async def stream_steps(self, message):
                yield ("bot_text", "reply")

        app.pm.create_active_agent.return_value = MockSubagent()

        tool = ManageSubagentTool()
        res = str(await tool.execute({"action": "send_message", "session_id": "sub-noreg", "message": "hi"}, ctx=app))
        self.assertIn("message sent to sub-noreg", res)

    async def test_send_message_with_worktree_and_host(self):
        sess = self.store.create_subagent(
            parent_id="sess-main",
            subagent_id="sub-wt",
            role="worker",
            title="Worktree task",
            prompt="prompt",
            status="completed",
            project_dir="/tmp/worktree",
            branch_name="feature-test",
        )
        app, spy = self._app_with_widget(sess)
        app.project_dir = "/tmp/parent"
        app.pm.get_active_provider_key.return_value = "openai"

        class MockSubagent:
            def __init__(self):
                self.provider_key = "openai"

            async def stream_steps(self, message):
                yield ("bot_text", "report done")

        subagent_inst = MockSubagent()
        sess.agent = subagent_inst

        with patch("core.infrastructure.runtime.subagent_worktree.SubagentWorktreeManager.ensure_worktree_available_async", new_callable=AsyncMock) as mock_wt:
            mock_wt.return_value = "/tmp/worktree"
            tool = ManageSubagentTool()
            res = str(await tool.execute({"action": "send_message", "session_id": "sub-wt", "message": "give report"}, ctx=app))
            self.assertIn("message sent to sub-wt", res)
            mock_wt.assert_awaited_once_with(sess, parent_dir="/tmp/parent")

    async def test_manage_subagent_missing_session_id_self_healing(self):
        sess = self._mk_subagent("sub-1", role="worker")
        app, _ = self._app_with_widget(sess)
        tool = ManageSubagentTool()

        res_kill = str(await tool.execute({"action": "kill"}, ctx=app))
        self.assertIn("required for 'kill'", res_kill)
        self.assertIn("manage_subagent(action='list')", res_kill)

        res_msg = str(await tool.execute({"action": "send_message", "message": "hello"}, ctx=app))
        self.assertIn("required for 'send_message'", res_msg)
        self.assertIn("manage_subagent(action='list')", res_msg)


if __name__ == "__main__":
    unittest.main()

