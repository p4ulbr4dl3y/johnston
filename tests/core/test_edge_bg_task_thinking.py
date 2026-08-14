"""Edge-case tests for core.tasks.shell_task + core.infrastructure.runtime.thinking_effort.

Focused on finding bugs, not duplicating existing suites.
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from core.tasks.manager import TaskManager
from core.tasks.shell_task import ShellTask
from core.tasks.task import TaskStatus
from core.infrastructure.runtime.thinking_effort import (
    GEMINI_25_THINKING_BUDGET_BY_EFFORT,
    SUPPORTED_THINKING_EFFORTS,
    build_anthropic_thinking_payload,
    build_gemini_thinking_config,
    build_ollama_thinking_payload,
    build_openai_thinking_kwargs,
    display_thinking_effort,
    normalize_thinking_effort,
)


# ---------------------------------------------------------------------------
# ShellTask: lifecycle edge cases
# ---------------------------------------------------------------------------
class TestShellTaskRunEdge(unittest.IsolatedAsyncioTestCase):
    def _make_reader(self, data: bytes = None):
        reader = asyncio.StreamReader()
        if data is not None:
            reader.feed_data(data)
        reader.feed_eof()
        return reader

    def _make_proc(self):
        proc = MagicMock()
        proc.wait = AsyncMock(return_value=0)
        sr = asyncio.StreamReader()
        sr.feed_eof()
        proc.stdout = sr
        proc.returncode = 0
        return proc

    def _make_rw_reader(self, chunks):
        """A reader-like object with an async .read() method."""
        class _R:
            def __init__(self, chunks):
                self.chunks = list(chunks)
            async def read(self, _n):
                if not self.chunks:
                    raise OSError("eof")
                return self.chunks.pop(0)
        return _R(chunks)

    async def test_reader_raises_immediately_is_handled(self):
        # Reader raises a raw exception on first read -> read loop must not propagate.
        t = ShellTask("t_boom", "cmd", None, reader=None)
        async def bad_read(_n):
            raise OSError("boom")
        t.reader = bad_read
        t.process = self._make_proc()
        t.start_reading()
        await t.read_task
        self.assertFalse(t.is_running)

    async def test_reader_raises_mid_stream_and_stops(self):
        # Reader yields one chunk then raises -> loop must stop and keep the chunk.
        t = ShellTask("t_mid", "cmd", None, reader=None)
        t.reader = self._make_rw_reader([b"first chunk\n"])
        t.process = self._make_proc()
        t.start_reading()
        await t.read_task
        self.assertFalse(t.is_running)
        self.assertIn("first chunk", t.get_formatted_output())

    async def test_reader_never_ends_can_be_killed(self):
        # A reader that never returns EOF must not hang; kill() must cancel it.
        t = ShellTask("t_hang", "cmd", None, reader=None)
        never = asyncio.Event()

        class _HangReader:
            async def read(self, _n):
                await never.wait()
                return b""

        t.reader = _HangReader()
        t.process = self._make_proc()
        t.start_reading()
        await asyncio.sleep(0.05)
        self.assertTrue(t.is_running)
        await t.kill()
        await asyncio.sleep(0.05)
        self.assertTrue(t.read_task.done() or t.read_task.cancelled())
        # Clean up the still-pending reader wait.
        never.set()
        t.read_task.cancel()

    async def test_restart_after_read_task_done(self):
        # Calling start_reading again after completion should not crash.
        t = ShellTask("t_restart", "cmd", self._make_proc())
        t.start_reading()
        await t.read_task
        t.process = self._make_proc()
        t.start_reading()
        await t.read_task


class TestShellTaskKillEdge(unittest.IsolatedAsyncioTestCase):
    def _make_proc(self):
        proc = MagicMock()
        proc.wait = AsyncMock(return_value=0)
        sr = asyncio.StreamReader()
        sr.feed_eof()
        proc.stdout = sr
        proc.returncode = 0
        return proc

    async def test_double_async_kill(self):
        proc = MagicMock()
        proc.pid = 99999
        proc.wait = AsyncMock(return_value=0)
        t = ShellTask("t_dk", "cmd", proc)
        await asyncio.gather(t.kill(), t.kill(), return_exceptions=True)
        self.assertFalse(t.is_running)
        self.assertTrue(t.was_killed)

    async def test_kill_after_completed(self):
        t = ShellTask("t_done", "cmd", self._make_proc())
        t.start_reading()
        await t.read_task
        await t.kill()
        self.assertFalse(t.is_running)

    async def test_kill_sync_after_completed(self):
        t = ShellTask("t_done2", "cmd", self._make_proc())
        t.start_reading()
        await t.read_task
        t.kill_sync()
        self.assertFalse(t.is_running)

    async def test_kill_with_none_process(self):
        t = ShellTask("t_np", "cmd", None)
        await t.kill()
        self.assertFalse(t.is_running)
        self.assertTrue(t.was_killed)

    async def test_kill_mid_read_cancels_reader(self):
        t = ShellTask("t_midkill", "cmd", None, reader=None)
        never = asyncio.Event()

        async def never_read(_n):
            await never.wait()
            return b""

        t.reader = never_read
        t.process = self._make_proc()
        t.start_reading()
        await asyncio.sleep(0.05)
        await t.kill()
        self.assertTrue(t.read_task.cancelled() or t.read_task.done())


class TestShellTaskStateAndCleanup(unittest.TestCase):
    def test_move_to_background_sets_event(self):
        t = ShellTask("t_bg", "cmd", None)
        t.move_to_background()
        self.assertTrue(t.is_background)
        self.assertTrue(t.background_event.is_set())

    def test_send_input_after_finish_returns_not_running(self):
        t = ShellTask("t_s", "cmd", None)
        t.status = TaskStatus.COMPLETED
        self.assertFalse(t.is_running)


class TestKillAllEdge(unittest.IsolatedAsyncioTestCase):
    def _make_proc(self):
        proc = MagicMock()
        proc.wait = AsyncMock(return_value=0)
        sr = asyncio.StreamReader()
        sr.feed_eof()
        proc.stdout = sr
        proc.returncode = 0
        return proc

    async def test_kill_all_handles_done_read_task(self):
        t = ShellTask("t_dn", "cmd", self._make_proc())
        t.start_reading()
        await t.read_task
        mgr = TaskManager()
        mgr.register(t)
        await mgr.kill_all()
        self.assertTrue(t.read_task.done())

    async def test_kill_all_empty(self):
        mgr = TaskManager()
        await mgr.kill_all()


# ---------------------------------------------------------------------------
# thinking_effort: parsing / boundaries / determinism / mutation
# ---------------------------------------------------------------------------
class TestThinkingEffortNormalize(unittest.TestCase):
    def test_none_and_falsy(self):
        self.assertIsNone(normalize_thinking_effort(None))
        self.assertIsNone(normalize_thinking_effort(""))
        self.assertIsNone(normalize_thinking_effort("   "))

    def test_invalid_values(self):
        # NOTE: normalize strips+lowercases, so "low\n" is a VALID level.
        for bad in ("giga", "auto ", "LOW-effort", "0.5", "1"):
            self.assertIsNone(normalize_thinking_effort(bad), bad)
        self.assertEqual(normalize_thinking_effort("low\n"), "low")

    def test_numeric_inputs(self):
        # Numeric effort values are not valid levels -> None (no crash).
        self.assertIsNone(normalize_thinking_effort(0))
        self.assertIsNone(normalize_thinking_effort(1.0))
        self.assertIsNone(normalize_thinking_effort(999999))
        self.assertIsNone(normalize_thinking_effort(-5))

    def test_case_insensitive(self):
        for v in ("LOW", "lOw", "LoW"):
            self.assertEqual(normalize_thinking_effort(v), "low")

    def test_auto_variants(self):
        for v in ("auto", "unset", "none", "AUTO"):
            self.assertIsNone(normalize_thinking_effort(v))

    def test_display_fallback(self):
        self.assertEqual(display_thinking_effort(None), "auto")
        self.assertEqual(display_thinking_effort(""), "auto")
        self.assertEqual(display_thinking_effort("high"), "high")

    def test_mutation_no_input_change(self):
        s = "  HIGH  "
        display_thinking_effort(s)
        self.assertEqual(s, "  HIGH  ")


class TestThinkingEffortBuilders(unittest.TestCase):
    def test_every_valid_effort_has_all_keys(self):
        for e in SUPPORTED_THINKING_EFFORTS:
            self.assertEqual(
                build_openai_thinking_kwargs(e), {"reasoning_effort": e}
            )
            self.assertEqual(
                build_anthropic_thinking_payload(e), {"output_config": {"effort": e}}
            )
            self.assertEqual(build_ollama_thinking_payload(e), {"think": e})
            g25 = build_gemini_thinking_config("gemini-2.5-flash", e)
            self.assertEqual(g25["thinkingBudget"], GEMINI_25_THINKING_BUDGET_BY_EFFORT[e])
            self.assertIn("includeThoughts", g25)

    def test_valid_efforts_monotonic_budget(self):
        budgets = [GEMINI_25_THINKING_BUDGET_BY_EFFORT[e] for e in ("low", "medium", "high")]
        self.assertEqual(budgets, sorted(budgets))
        self.assertGreaterEqual(budgets[1], budgets[0])
        self.assertGreaterEqual(budgets[2], budgets[1])

    def test_gemini_3_efforts_all_valid(self):
        for e in SUPPORTED_THINKING_EFFORTS:
            self.assertEqual(
                build_gemini_thinking_config("gemini-3.0-pro", e), {"thinkingLevel": e}
            )

    def test_invalid_effort_builds_empty(self):
        self.assertEqual(build_openai_thinking_kwargs("bogus"), {})
        self.assertEqual(build_anthropic_thinking_payload("bogus"), {})
        self.assertEqual(build_ollama_thinking_payload("bogus"), {})
        self.assertIsNone(build_gemini_thinking_config("gemini-2.5-flash", "bogus"))

    def test_negative_and_huge_no_crash(self):
        self.assertEqual(build_openai_thinking_kwargs(-1), {})
        self.assertEqual(build_openai_thinking_kwargs(10**12), {})

    def test_deterministic(self):
        # Same input -> same normalized output, no RNG involved.
        self.assertEqual(normalize_thinking_effort("high"), normalize_thinking_effort("high"))
        self.assertEqual(build_gemini_thinking_config("gemini-2.5", "low"),
                         build_gemini_thinking_config("gemini-2.5", "low"))

    def test_gemini_2_5_contains_3_suffix_still_2_5(self):
        # "gemini-2.5" is a substring of "gemini-25" only by id; check boundary.
        cfg = build_gemini_thinking_config("gemini-2.5-flash", "high")
        self.assertEqual(cfg["thinkingBudget"], GEMINI_25_THINKING_BUDGET_BY_EFFORT["high"])


if __name__ == "__main__":
    unittest.main()
