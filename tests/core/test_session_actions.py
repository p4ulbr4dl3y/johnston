"""Unit tests for pure-core session actions (no UI/Textual)."""
import asyncio
import unittest

from core.application.session.actions import (
    compact_session,
    new_session,
    rewind_session,
)


class MockAgent:
    def __init__(self):
        self.history = []
        self.compact_called = False
        self.tokens_input = 0
        self.tokens_output = 0
        self.tokens_cache_read = 0
        self.last_context_tokens = 0
        self.total_tokens = 0
        self.cost_usd = 0.0

    def clear_history(self):
        self.history = []

    def truncate_history_to_user_message(self, idx):
        self.history = self.history[: idx + 1]

    async def compact_history(self):
        self.compact_called = True
        return True, "History compacted"


class TestNewSession(unittest.IsolatedAsyncioTestCase):
    async def test_new_session_returns_and_uses_store_agent(self):
        class Sm:
            def __init__(self):
                self.created = []

            def generate_session_id(self):
                return "new-id"

            def create_main(self, sid):
                self.created.append(sid)

        sm = Sm()
        agent = MockAgent()
        agent.history = [{"role": "user", "content": "old"}]

        calls = {"cancel_workers": 0, "kill_all": 0, "subagents": 0}

        def cancel_workers():
            calls["cancel_workers"] += 1

        async def kill_all_tasks():
            calls["kill_all"] += 1

        def cancel_subagents():
            calls["subagents"] += 1

        sid = await new_session(
            sm,
            agent,
            cancel_workers=cancel_workers,
            kill_all_tasks=kill_all_tasks,
            cancel_subagents=cancel_subagents,
        )

        self.assertEqual(sid, "new-id")
        self.assertEqual(sm.created, ["new-id"])
        self.assertEqual(agent.history, [])
        self.assertEqual(calls, {"cancel_workers": 1, "kill_all": 1, "subagents": 1})

    async def test_new_session_synchronous_kill_all_tasks_callback(self):
        class Sm:
            def generate_session_id(self):
                return "new-sync-id"

            def create_main(self, sid):
                pass

        sm = Sm()
        agent = MockAgent()
        calls = {"kill_all": 0}

        def sync_kill_all():
            calls["kill_all"] += 1

        sid = await new_session(
            sm,
            agent,
            cancel_workers=lambda: None,
            kill_all_tasks=sync_kill_all,
            cancel_subagents=lambda: None,
        )
        self.assertEqual(sid, "new-sync-id")
        self.assertEqual(calls["kill_all"], 1)


class TestCompactSession(unittest.IsolatedAsyncioTestCase):
    async def test_compact_success(self):
        agent = MockAgent()

        begin = []
        divider = []
        footer = []
        saved = []

        outcome = await compact_session(
            agent,
            save_session_cb=lambda: saved.append(True),
            on_begin=lambda: begin.append(True),
            on_divider_update=divider.append,
            refresh_footer_cb=lambda: footer.append(True),
        )

        self.assertTrue(outcome.success)
        self.assertTrue(agent.compact_called)
        self.assertEqual(outcome.status.value, "completed")
        self.assertEqual(begin, [True])
        self.assertEqual(divider, ["Session Compacted"])
        self.assertEqual(footer, [True])
        self.assertEqual(saved, [True])

    async def test_compact_success_with_tokens(self):
        class Agent(MockAgent):
            async def compact_history(self):
                return True, "History compacted successfully (12,000 → 3,000 tokens)"

        outcome = await compact_session(
            Agent(),
            save_session_cb=lambda: None,
            on_begin=lambda: None,
            on_divider_update=lambda _t: None,
            refresh_footer_cb=lambda: None,
        )
        self.assertTrue(outcome.success)
        self.assertEqual(outcome.tokens.before, 12000)
        self.assertEqual(outcome.tokens.after, 3000)
        self.assertEqual(outcome.title, "Session Compacted (12,000 → 3,000 tokens)")

    async def test_compact_failure(self):
        class FailAgent(MockAgent):
            async def compact_history(self):
                return False, "Compaction failed (some err)"
        agent = FailAgent()

        divider = []
        saved = []
        footer = []

        outcome = await compact_session(
            agent,
            save_session_cb=lambda: saved.append(True),
            on_begin=lambda: None,
            on_divider_update=divider.append,
            refresh_footer_cb=lambda: footer.append(True),
        )

        self.assertFalse(outcome.success)
        self.assertEqual(outcome.status.value, "failed")
        self.assertEqual(outcome.message, "Compaction failed (some err)")
        self.assertEqual(divider, ["Compaction Failed"])
        self.assertEqual(saved, [True])
        self.assertEqual(footer, [])

    async def test_compact_no_agent(self):
        divider = []
        outcome = await compact_session(
            None,
            save_session_cb=lambda: None,
            on_begin=lambda: None,
            on_divider_update=divider.append,
            refresh_footer_cb=lambda: None,
        )
        self.assertFalse(outcome.success)
        self.assertEqual(outcome.message, "No active agent found")

    async def test_compact_cancelled_saves_and_updates_divider(self):
        class CancelAgent(MockAgent):
            async def compact_history(self):
                raise asyncio.CancelledError()

        divider = []
        saved = []

        with self.assertRaises(asyncio.CancelledError):
            await compact_session(
                CancelAgent(),
                save_session_cb=lambda: saved.append(True),
                on_begin=lambda: None,
                on_divider_update=divider.append,
                refresh_footer_cb=lambda: None,
            )

        self.assertEqual(divider, ["Compaction Cancelled"])
        self.assertEqual(saved, [True])


class TestRewindSession(unittest.IsolatedAsyncioTestCase):
    async def test_rewind_full_clear(self):
        agent = MockAgent()
        agent.history = [{"role": "user", "content": "First"}]
        agent.tokens_input = 4000
        agent.tokens_output = 3000
        agent.tokens_cache_read = 2000
        agent.last_context_tokens = 9000
        agent.total_tokens = 7000
        agent.cost_usd = 0.12

        rolled = []
        loaded = []
        saved = []
        footer = []

        await asyncio.to_thread(
            rewind_session,
            agent,
            None,
            None,
            [(0, "First message")],
            0,
            rollback_ui=rolled.append,
            load_text_into_input=loaded.append,
            save_session_cb=lambda: saved.append(True),
            refresh_footer_cb=lambda: footer.append(True),
        )

        self.assertEqual(rolled, [-1])
        self.assertEqual(loaded, ["First message"])
        self.assertEqual(saved, [True])
        self.assertEqual(footer, [True])
        self.assertEqual(agent.history, [])
        self.assertEqual(agent.tokens_input, 0)
        self.assertEqual(agent.cost_usd, 0.0)

    async def test_rewind_truncate(self):
        called_idx = []

        def do_truncate(idx):
            called_idx.append(idx)
            agent.history = [{"role": "user", "content": "Msg 0"}]

        agent = MockAgent()
        agent.history = [
            {"role": "user", "content": "Msg 0"},
            {"role": "assistant", "content": "Resp 0"},
            {"role": "user", "content": "Msg 1"},
            {"role": "assistant", "content": "Resp 1"},
        ]
        agent.tokens_input = 4000
        agent.tokens_output = 3000
        agent.tokens_cache_read = 2000
        agent.last_context_tokens = 5000
        agent.total_tokens = 7000
        agent.cost_usd = 0.12
        agent.truncate_history_to_user_message = do_truncate

        await asyncio.to_thread(
            rewind_session,
            agent,
            None,
            None,
            [(0, "Msg 0"), (2, "Msg 1")],
            2,
            rollback_ui=lambda i: None,
            load_text_into_input=lambda t: None,
            save_session_cb=lambda: None,
            refresh_footer_cb=lambda: None,
        )

        self.assertEqual(called_idx, [1])
        self.assertEqual(len(agent.history), 1)
        self.assertEqual(agent.history[0]["content"], "Msg 0")
        # Cumulative metrics reset on the truncate path too, but the freshly
        # recomputed context-token estimate survives.
        self.assertEqual(agent.tokens_input, 0)
        self.assertEqual(agent.tokens_output, 0)
        self.assertEqual(agent.tokens_cache_read, 0)
        self.assertEqual(agent.total_tokens, 0)
        self.assertEqual(agent.cost_usd, 0.0)
        self.assertEqual(agent.last_context_tokens, 5000)

    async def test_rewind_truncates_store_transcript(self):
        class Session:
            def __init__(self):
                self.messages = [
                    {"type": "user", "text": "Msg 0", "show_in_ui": True},
                    {"type": "bot", "text": "Resp 0"},
                    {"type": "user", "text": '<system_note kind="interrupted" phase="bot"></system_note>', "show_in_ui": True},
                    {"type": "user", "text": "Msg 1", "show_in_ui": True},
                    {"type": "bot", "text": "Resp 1"},
                ]

        agent = MockAgent()
        agent.history = [{"role": "user", "content": "Msg 0"}, {"role": "user", "content": "Msg 1"}]
        session = Session()

        await asyncio.to_thread(
            rewind_session,
            agent,
            None,
            None,
            [(0, "Msg 0"), (3, "Msg 1")],
            3,
            session=session,
            rollback_ui=lambda i: None,
            load_text_into_input=lambda t: None,
            save_session_cb=lambda: None,
            refresh_footer_cb=lambda: None,
        )

        # Rolled-back turn (Msg 1 + Resp 1) and the hidden interruption note
        # are dropped from the store transcript; UI indexing counts only visible
        # user turns, and the [System Note] turn is skipped.
        self.assertEqual(
            session.messages,
            [{"type": "user", "text": "Msg 0", "show_in_ui": True}, {"type": "bot", "text": "Resp 0"}],
        )

    async def test_rewind_full_clear_truncates_whole_transcript(self):
        class Session:
            def __init__(self):
                self.messages = [
                    {"type": "user", "text": "Msg 0", "show_in_ui": True},
                    {"type": "bot", "text": "Resp 0"},
                ]

        agent = MockAgent()
        agent.history = [{"role": "user", "content": "Msg 0"}]
        session = Session()

        await asyncio.to_thread(
            rewind_session,
            agent,
            None,
            None,
            [(0, "Msg 0")],
            0,
            session=session,
            rollback_ui=lambda i: None,
            load_text_into_input=lambda t: None,
            save_session_cb=lambda: None,
            refresh_footer_cb=lambda: None,
        )

        self.assertEqual(session.messages, [])

    async def test_rewind_keeps_git_restore_task_on_agent(self):
        agent = MockAgent()
        agent.history = [{"role": "user", "content": "Msg 0"}]

        # Called directly on the event loop (as RewindCommand does); the
        # background git restore needs a running loop to spawn.
        rewind_session(
            agent,
            "sess-1",
            "/tmp/project",
            [(0, "Msg 0")],
            0,
            rollback_ui=lambda i: None,
            load_text_into_input=lambda t: None,
            save_session_cb=lambda: None,
            refresh_footer_cb=lambda: None,
        )

        task = getattr(agent, "rewind_git_restore_task", None)
        self.assertIsNotNone(task)
        # Give the background restore a chance to run; it should fail cleanly
        # on a non-git target and finish without raising.
        await asyncio.wait_for(asyncio.shield(task), timeout=5)
        self.assertTrue(task.done())

    async def test_rewind_without_git_restore(self):
        from unittest.mock import patch

        from core.infrastructure.storage.git_checkpoint import GitCheckpointManager

        agent = MockAgent()
        agent.history = [{"role": "user", "content": "Msg 0"}]

        with patch.object(GitCheckpointManager, "restore_checkpoint") as mock_restore:
            with patch.object(GitCheckpointManager, "purge_checkpoints_after") as mock_purge:
                rewind_session(
                    agent,
                    "sess-1",
                    "/tmp/project",
                    [(0, "Msg 0")],
                    0,
                    restore_git=False,
                    rollback_ui=lambda i: None,
                    load_text_into_input=lambda t: None,
                    save_session_cb=lambda: None,
                    refresh_footer_cb=lambda: None,
                )
                task = getattr(agent, "rewind_git_restore_task", None)
                if task:
                    await asyncio.wait_for(asyncio.shield(task), timeout=5)

                mock_restore.assert_not_called()
                mock_purge.assert_called_once_with("sess-1", 0, project_path="/tmp/project")

        self.assertEqual(agent.history, [])

    async def test_get_rewind_git_stats_with_session(self):
        from unittest.mock import MagicMock

        from core.application.session.actions import get_rewind_git_stats

        mock_cm = MagicMock()
        mock_cm.is_valid_checkpoint_target.return_value = True
        mock_cm.get_diff_details_batch.return_value = {
            0: ("1 file, +2 / -1", ["file_a.py"]),
            1: ("no changes", []),
        }

        class MockSession:
            def __init__(self):
                self.messages = [
                    {"type": "user", "text": "turn 0", "show_in_ui": True, "touched_files": ["file_a.py"]},
                    {"type": "bot", "text": "reply 0"},
                    {"type": "user", "text": "turn 1", "show_in_ui": True, "touched_files": []},
                    {"type": "bot", "text": "reply 1"},
                ]

        session = MockSession()
        entries = await get_rewind_git_stats(
            "sess-1",
            [(0, "turn 0"), (1, "turn 1")],
            "/tmp/project",
            checkpoint_manager=mock_cm,
            session=session,
        )

        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].git_stats, "1 file, +2 / -1")
        self.assertEqual(entries[0].changed_files, ["file_a.py"])
        self.assertEqual(entries[1].git_stats, "no changes")

        # Verify get_diff_details_batch was called with scoped_files
        mock_cm.get_diff_details_batch.assert_called_once_with(
            "sess-1",
            [0, 1],
            project_path="/tmp/project",
            scoped_files={0: ["file_a.py"], 1: []},
        )

    async def test_rewind_session_passes_files_to_restore(self):
        from unittest.mock import patch

        from core.infrastructure.storage.git_checkpoint import GitCheckpointManager

        agent = MockAgent()
        agent.history = [{"role": "user", "content": "turn 0"}, {"role": "user", "content": "turn 1"}]

        class MockSession:
            def __init__(self):
                self.messages = [
                    {"type": "user", "text": "turn 0", "show_in_ui": True, "touched_files": ["a.txt"]},
                    {"type": "user", "text": "turn 1", "show_in_ui": True, "touched_files": ["b.txt"]},
                ]

        session = MockSession()

        with patch.object(GitCheckpointManager, "restore_checkpoint") as mock_restore:
            with patch.object(GitCheckpointManager, "purge_checkpoints_after") as mock_purge:
                rewind_session(
                    agent,
                    "sess-1",
                    "/tmp/project",
                    [(0, "turn 0"), (1, "turn 1")],
                    0,
                    restore_git=True,
                    session=session,
                    rollback_ui=lambda i: None,
                    load_text_into_input=lambda t: None,
                    save_session_cb=lambda: None,
                    refresh_footer_cb=lambda: None,
                )
                task = getattr(agent, "rewind_git_restore_task", None)
                if task:
                    await asyncio.wait_for(asyncio.shield(task), timeout=5)

                mock_restore.assert_called_once_with(
                    "sess-1", 0, project_path="/tmp/project", files_to_restore=["a.txt", "b.txt"]
                )
                mock_purge.assert_called_once_with("sess-1", 0, project_path="/tmp/project")

    async def test_forked_session_rewind_keeps_parent_intact(self):
        import tempfile

        from core.infrastructure.storage.session_store import SessionStore

        with tempfile.TemporaryDirectory() as tmpdir:
            sm = SessionStore(project_path=tmpdir)
            parent = sm.create_main()
            parent.title = "Parent"
            parent.prompt = "prompt 0"
            parent.messages = [
                {"type": "user", "text": "prompt 0", "show_in_ui": True},
                {"type": "bot", "text": "answer 0"},
                {"type": "user", "text": "prompt 1", "show_in_ui": True},
                {"type": "bot", "text": "answer 1"},
                {"type": "user", "text": "prompt 2", "show_in_ui": True},
                {"type": "bot", "text": "answer 2"},
            ]
            sm.save(parent)

            # Fork at prompt 1 (up_to_msg_index=1 -> preserves turn 0 before prompt 1)
            forked = sm.fork_session(parent.id, new_title="Forked Branch", up_to_msg_index=1)
            self.assertIsNotNone(forked)
            self.assertEqual(len(forked.messages), 2)  # prompt 0, bot 0

            # Rewind forked session to turn 0 (first user message)
            agent = MockAgent()
            agent.history = [
                {"role": "user", "content": "prompt 0"},
                {"role": "assistant", "content": "answer 0"},
                {"role": "user", "content": "prompt 1"},
                {"role": "assistant", "content": "answer 1"},
            ]

            forked_user_msgs = [(0, "prompt 0"), (2, "prompt 1")]
            rewind_session(
                agent,
                forked.id,
                tmpdir,
                forked_user_msgs,
                0,
                restore_git=False,
                session=forked,
                rollback_ui=lambda i: None,
                load_text_into_input=lambda t: None,
                save_session_cb=lambda: sm.save(forked),
                refresh_footer_cb=lambda: None,
            )

            # Forked session truncated
            self.assertEqual(len(forked.messages), 0)
            self.assertEqual(agent.history, [])

            # Parent session MUST remain completely unchanged
            parent_reloaded = sm.get(parent.id)
            self.assertEqual(len(parent_reloaded.messages), 6)
            self.assertEqual(parent_reloaded.messages[4]["text"], "prompt 2")

    async def test_rewind_session_cleans_up_subagents_and_tasks(self):
        from unittest.mock import MagicMock

        from core.application.session.actions import restore_plan_from_messages

        # Test restore_plan_from_messages
        plan_msgs = [
            {"type": "user", "text": "build feature"},
            {"type": "tool", "tool_type": "update_plan", "args": {"plan": [{"title": "step 1", "status": "in_progress"}], "explanation": "doing 1"}},
            {"type": "bot", "text": "working on step 1"},
        ]
        plan, exp = restore_plan_from_messages(plan_msgs)
        self.assertEqual(len(plan), 1)
        self.assertEqual(exp, "doing 1")

        # Test subagent and task cleanup on rewind
        mock_store = MagicMock()
        mock_child_sub = MagicMock(id="sub-child-1")
        mock_child_sub.async_task = MagicMock(done=lambda: False)
        mock_store.children.return_value = [mock_child_sub]

        mock_tm = MagicMock()
        mock_task = MagicMock(id="task-123", is_running=True)
        mock_tm._tasks = {"task-123": mock_task}

        sess = MagicMock(id="parent-1")
        sess.messages = [
            {"type": "user", "text": "turn 0", "show_in_ui": True},
            {"type": "bot", "text": "ans 0"},
            {"type": "user", "text": "turn 1", "show_in_ui": True},
            {"type": "tool", "tool_type": "invoke_subagent", "args": {"session_id": "sub-child-1"}},
            {"type": "tool", "tool_type": "shell", "background_task_id": "task-123"},
            {"type": "bot", "text": "ans 1"},
        ]

        agent = MockAgent()
        agent.history = [
            {"role": "user", "content": "turn 0"},
            {"role": "assistant", "content": "ans 0"},
            {"role": "user", "content": "turn 1"},
            {"role": "assistant", "content": "ans 1"},
        ]

        rewind_session(
            agent,
            "parent-1",
            "/tmp",
            [(0, "turn 0"), (2, "turn 1")],
            2,
            restore_git=False,
            session=sess,
            rollback_ui=lambda i: None,
            load_text_into_input=lambda t: None,
            save_session_cb=lambda: None,
            refresh_footer_cb=lambda: None,
            store=mock_store,
            task_manager=mock_tm,
        )

        mock_child_sub.async_task.cancel.assert_called_once()
        mock_store.delete.assert_called_once_with("sub-child-1")
        mock_tm.drop.assert_called_once_with("task-123")

    def test_touched_files_untracked_turn_returns_none(self):
        from core.application.session.actions import _touched_files

        # When all turns have tracked lists, returns sorted union
        events_tracked = [
            {"touched_files": ["b.py"]},
            {"touched_files": ["a.py"]},
        ]
        self.assertEqual(_touched_files(events_tracked, 0), ["a.py", "b.py"])
        self.assertEqual(_touched_files(events_tracked, 1), ["a.py"])
        self.assertEqual(_touched_files(events_tracked, 2), [])

        # When any turn in the slice is untracked (None), returns None
        events_with_untracked = [
            {"touched_files": ["b.py"]},
            {"touched_files": None},
        ]
        self.assertIsNone(_touched_files(events_with_untracked, 0))
        # When events list is empty, returns None
        self.assertIsNone(_touched_files([], 0))


if __name__ == "__main__":
    unittest.main()
