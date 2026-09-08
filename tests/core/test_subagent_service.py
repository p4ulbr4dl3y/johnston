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

        s3 = AgentSession(session_id="sub-3", status=SessionStatus.COMPLETED)
        self.assertEqual(resolve_subagent_display_status(s3), "completed")

        s4 = AgentSession(session_id="sub-4", status=SessionStatus.CANCELLED)
        self.assertEqual(resolve_subagent_display_status(s4), "cancelled")

        s5 = AgentSession(session_id="sub-5", status="cancelled")
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
        self.assertEqual(sess.pending_messages, [])
        self.assertEqual(res.content, "[killed sub-1]")
        # M6 single-writer: the sync path only cancels; the cancelled task's
        # own teardown owns the terminal finish + save. Status stays live
        # ("running") until that teardown runs and no sync save happens here.
        self.assertEqual(sess.status, SessionStatus.RUNNING)
        store.save.assert_not_called()

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

    def test_kill_subagent_stale_done_task_still_finalized(self):
        """A6: a session whose async_task already finished (crashed/completed
        without follow-up) but whose status is still "running" is a kill
        target too: it must be finalized (status flipped + saved) instead of
        being bailed out of before the status flip. task.cancel() is not
        called on a done task."""
        store = MagicMock()
        sess = AgentSession(session_id="sub-stale", status=SessionStatus.RUNNING)
        task = FakeTask(done=True)
        sess.async_task = task

        res = SubagentService.kill_subagent(sess, store)
        self.assertEqual(res.content, "[killed sub-stale]")
        self.assertFalse(task.cancelled)
        self.assertEqual(sess.status, SessionStatus.CANCELLED)
        store.save.assert_called_once_with(sess)
        status_changes = [m for m in sess.messages if m.get("type") == "status_change"]
        self.assertEqual(len(status_changes), 1)
        self.assertEqual(status_changes[0]["error"], "Cancelled via subagent tool")

    def test_kill_subagent_no_task_finalizes(self):
        """A6/M6 fallback: without an async_task no task teardown can run, so
        the sync finish+save must finalize the session."""
        store = MagicMock()
        sess = AgentSession(session_id="sub-no-task", status=SessionStatus.RUNNING)
        res = SubagentService.kill_subagent(sess, store)
        self.assertEqual(res.content, "[killed sub-no-task]")
        self.assertEqual(sess.status, SessionStatus.CANCELLED)
        store.save.assert_called_once_with(sess)

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
        # M6 single-writer: live cancelled tasks own the terminal finish+save;
        # the sync path does not write (status stays live until teardown).
        self.assertEqual(s1.status, SessionStatus.RUNNING)
        self.assertEqual(s2.status, "active")
        store.save.assert_not_called()

    def test_cancel_running_subagents_stale_task_fallback_finalizes(self):
        """A6/M6 fallback: a session whose async_task already finished but
        whose status is still "running" is cancelled too — the sync finish+save
        finalizes it since no task teardown can run."""
        store = MagicMock()
        sess = AgentSession(session_id="sub-stale", status=SessionStatus.RUNNING)
        t = FakeTask(done=True)
        sess.async_task = t

        store.children.return_value = [sess]
        count = SubagentService.cancel_running_subagents(store, parent_id="parent-1")
        self.assertEqual(count, 1)
        self.assertFalse(t.cancelled)
        self.assertEqual(sess.status, SessionStatus.CANCELLED)
        store.save.assert_called_once_with(sess)

    def test_cancel_running_subagents_none_store(self):
        self.assertEqual(SubagentService.cancel_running_subagents(None), 0)

    async def test_spawn_empty_prompt_error(self):
        ctx = MagicMock()
        res = await SubagentService.spawn_subagent(prompt="", title="test", ctx=ctx)
        self.assertTrue(res.is_error)
        self.assertIn("task", str(res.content))

    async def test_spawn_registers_subagent_task_in_task_manager(self):
        from unittest.mock import AsyncMock, patch

        from core.infrastructure.tasks.manager import TaskManager
        from core.infrastructure.tasks.subagent_task import SubagentTask

        task_mgr = TaskManager()
        ctx = MagicMock()
        ctx.task_manager = task_mgr
        ctx.host = MagicMock()
        ctx.session_id = "parent-1"
        ctx.project_dir = "/tmp/fake"
        agent = MagicMock()
        ctx.create_agent.return_value = agent

        store = MagicMock()
        sess = AgentSession(session_id="sub-task-1", status=SessionStatus.RUNNING)
        store.create_subagent.return_value = sess
        store.list.return_value = []
        store.children.return_value = []

        wt_mgr = MagicMock()
        wt_mgr.is_git_repo.return_value = False

        with (
            patch("core.application.session.subagent_service.get_session_store", return_value=store),
            patch("core.application.session.subagent_service.record_subagent_session"),
            patch("core.application.session.stream.configure_subagent_agent"),
            patch("core.application.session.stream.run_subagent_stream_bg", new_callable=AsyncMock),
        ):
            res = await SubagentService.spawn_subagent(
                prompt="work on task",
                title="worker subagent",
                ctx=ctx,
                worktree_manager_cls=wt_mgr,
            )
            self.assertFalse(res.is_error)
            registered = task_mgr.get("sub-task-1")
            self.assertIsNotNone(registered)
            self.assertIsInstance(registered, SubagentTask)
            self.assertEqual(registered.session, sess)


class TestSubagentTaskUnit(unittest.IsolatedAsyncioTestCase):
    async def test_subagent_task_lifecycle_and_status(self):
        from core.infrastructure.tasks.subagent_task import SubagentTask
        from core.infrastructure.tasks.task import TaskStatus

        sess = AgentSession(session_id="sub-task-2", status=SessionStatus.RUNNING, title="My Subagent")
        task_mock = FakeTask(done=False)
        sess.async_task = task_mock
        store = MagicMock()

        task = SubagentTask(sess, store, task_mock)
        self.assertEqual(task.kind, "subagent")
        self.assertEqual(task.status, TaskStatus.RUNNING)
        self.assertTrue(task.is_running)

        await task.kill()
        self.assertEqual(task.status, TaskStatus.KILLED)
        self.assertFalse(task.is_running)
        self.assertTrue(task_mock.cancelled)
