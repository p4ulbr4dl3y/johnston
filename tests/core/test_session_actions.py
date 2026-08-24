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
                    {"type": "user", "text": "[System Note: Response interrupted by user]", "show_in_ui": True},
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


if __name__ == "__main__":
    unittest.main()
