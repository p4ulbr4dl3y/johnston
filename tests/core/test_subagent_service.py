"""Unit tests for SubagentService application service."""

import unittest
from unittest.mock import MagicMock

from core.application.session.subagent_service import (
    SubagentService,
    is_active_subagent,
    resolve_subagent_display_status,
)
from core.domain.entities.session import AgentSession, SessionStatus


class FakeTask:
    def __init__(self, done: bool = False):
        self._done = done
        self.cancelled = False

    def done(self) -> bool:
        return self._done

    def cancel(self) -> None:
        self.cancelled = True


class TestSubagentServiceStatus(unittest.TestCase):
    def test_is_active_subagent_with_running_async_task(self):
        sess = AgentSession(session_id="sub-1", status=SessionStatus.COMPLETED)
        sess.async_task = FakeTask(done=False)
        self.assertTrue(is_active_subagent(sess))

    def test_is_active_subagent_with_done_task_and_completed_status(self):
        sess = AgentSession(session_id="sub-1", status=SessionStatus.COMPLETED)
        sess.async_task = FakeTask(done=True)
        self.assertFalse(is_active_subagent(sess))

    def test_is_active_subagent_statuses(self):
        s_running = AgentSession(session_id="sub-1", status=SessionStatus.RUNNING)
        self.assertTrue(is_active_subagent(s_running))

        s_str_active = AgentSession(session_id="sub-2", status="active")
        self.assertTrue(is_active_subagent(s_str_active))

        s_str_running = AgentSession(session_id="sub-3", status="running")
        self.assertTrue(is_active_subagent(s_str_running))

        s_cancelled = AgentSession(session_id="sub-4", status=SessionStatus.CANCELLED)
        self.assertFalse(is_active_subagent(s_cancelled))

    def test_resolve_subagent_display_status(self):
        s1 = AgentSession(session_id="sub-1", status=SessionStatus.RUNNING)
        self.assertEqual(resolve_subagent_display_status(s1), "running")

        s2 = AgentSession(session_id="sub-2", status="active")
        self.assertEqual(resolve_subagent_display_status(s2), "running")

        s3 = AgentSession(session_id="sub-3", status="finished")
        self.assertEqual(resolve_subagent_display_status(s3), "completed")

        s4 = AgentSession(session_id="sub-4", status=SessionStatus.CANCELLED)
        self.assertEqual(resolve_subagent_display_status(s4), "cancelled")

        s5 = AgentSession(session_id="sub-5", status="killed")
        self.assertEqual(resolve_subagent_display_status(s5), "cancelled")

        s6 = AgentSession(session_id="sub-6", status="error")
        self.assertEqual(resolve_subagent_display_status(s6), "error")

        s7 = AgentSession(session_id="sub-7", status="custom_state")
        self.assertEqual(resolve_subagent_display_status(s7), "custom_state")


class TestSubagentServiceOperations(unittest.IsolatedAsyncioTestCase):
    def test_format_subagents_list(self):
        self.assertEqual(SubagentService.format_subagents_list([]), "[subagents 0]")

        s1 = AgentSession(session_id="sub-123", status=SessionStatus.RUNNING, role="explorer", title="Explore codebase")
        formatted = SubagentService.format_subagents_list([s1])
        self.assertIn("[subagents 1 | id|status|role|title]", formatted)
        self.assertIn("sub-123|running|explorer|Explore codebase", formatted)

    def test_kill_subagent_running(self):
        store = MagicMock()
        sess = AgentSession(session_id="sub-1", status=SessionStatus.RUNNING)
        sess.pending_messages = ["follow-up 1", "follow-up 2"]
        task = FakeTask(done=False)
        sess.async_task = task

        res = SubagentService.kill_subagent(sess, store)
        self.assertTrue(task.cancelled)
        self.assertEqual(sess.status, SessionStatus.CANCELLED)
        self.assertEqual(sess.pending_messages, [])
        store.save.assert_called_once_with(sess)
        self.assertEqual(res.content, "[killed sub-1]")

    def test_resolve_status_cancelled_with_undone_task(self):
        sess = AgentSession(session_id="sub-c", status=SessionStatus.CANCELLED)
        sess.async_task = FakeTask(done=False)
        # Should return 'cancelled', not 'running', even if cleanup task not yet finished
        self.assertEqual(resolve_subagent_display_status(sess), "cancelled")

    def test_kill_subagent_already_completed(self):
        store = MagicMock()
        sess = AgentSession(session_id="sub-2", status=SessionStatus.COMPLETED)
        res = SubagentService.kill_subagent(sess, store)
        self.assertEqual(res.content, "[killed sub-2]")
        store.save.assert_not_called()

    def test_cancel_running_subagents(self):
        store = MagicMock()
        s1 = AgentSession(session_id="sub-1", status=SessionStatus.RUNNING)
        t1 = FakeTask(done=False)
        s1.async_task = t1

        s2 = AgentSession(session_id="sub-2", status="active")
        t2 = FakeTask(done=False)
        s2.async_task = t2

        s3 = AgentSession(session_id="sub-3", status=SessionStatus.COMPLETED)

        store.children.return_value = [s1, s2, s3]
        count = SubagentService.cancel_running_subagents(store, parent_id="parent-1")
        self.assertEqual(count, 2)
        self.assertTrue(t1.cancelled)
        self.assertTrue(t2.cancelled)
        self.assertEqual(s1.status, SessionStatus.CANCELLED)
        self.assertEqual(s2.status, SessionStatus.CANCELLED)

    def test_cancel_running_subagents_none_store(self):
        self.assertEqual(SubagentService.cancel_running_subagents(None), 0)

    async def test_spawn_empty_prompt_error(self):
        ctx = MagicMock()
        res = await SubagentService.spawn_subagent(prompt="", title="test", ctx=ctx)
        self.assertTrue(res.is_error)
        self.assertIn("prompt", str(res.content))
