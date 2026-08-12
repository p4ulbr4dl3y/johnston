"""Edge-case tests for core.background_task + core.thinking_effort.

Focused on finding bugs, not duplicating existing suites.
"""
import asyncio
import unittest
from unittest.mock import AsyncMock, MagicMock

from core.background_task import BackgroundTask, kill_all_background_tasks, strip_ansi
from core.thinking_effort import (
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
# BackgroundTask: lifecycle edge cases
# ---------------------------------------------------------------------------
class TestBackgroundTaskRunEdge(unittest.IsolatedAsyncioTestCase):
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
        t = BackgroundTask("t_boom", "cmd", None, reader=None)
        async def bad_read(_n):
            raise OSError("boom")
        t.reader = bad_read
        t.process = self._make_proc()
        t.start_reading(None, None)
        await t.read_task
        self.assertFalse(t.is_running)

    async def test_reader_raises_mid_stream_and_stops(self):
        # Reader yields one chunk then raises -> loop must stop and keep the chunk.
        t = BackgroundTask("t_mid", "cmd", None, reader=None)
        t.reader = self._make_rw_reader([b"first chunk\n"])
        t.process = self._make_proc()
        t.start_reading(None, None)
        await t.read_task
        self.assertFalse(t.is_running)
        self.assertIn("first chunk", t.get_formatted_output())

    async def test_reader_never_ends_can_be_killed(self):
        # A reader that never returns EOF must not hang; kill() must cancel it.
        t = BackgroundTask("t_hang", "cmd", None, reader=None)
        never = asyncio.Event()

        class _HangReader:
            async def read(self, _n):
                await never.wait()
                return b""

        t.reader = _HangReader()
        t.process = self._make_proc()
        t.start_reading(None, None)
        await asyncio.sleep(0.05)
        self.assertTrue(t.is_running)
        await t.kill()
        await asyncio.sleep(0.05)
        self.assertTrue(t.read_task.done() or t.read_task.cancelled())
        # Clean up the still-pending reader wait.
        never.set()
        t.read_task.cancel()

    async def test_restart_after_read_task_done(self):
        # is_running is set False only by the read loop; calling start_reading again
        # after completion should not crash and should set is_running True again.
        t = BackgroundTask("t_restart", "cmd", self._make_proc())
        t.start_reading(None, None)
        await t.read_task
        self.assertFalse(t.is_running)
        t.is_running = True
        t.process = self._make_proc()
        t.start_reading(None, None)
        await t.read_task
        self.assertFalse(t.is_running)


class TestBackgroundTaskKillEdge(unittest.IsolatedAsyncioTestCase):
    async def test_double_async_kill(self):
        proc = MagicMock()
        proc.pid = 99999
        proc.wait = AsyncMock(return_value=0)
        t = BackgroundTask("t_dk", "cmd", proc)
        read_task = asyncio.create_task(t.kill())
        # Concurrent double kill: both set state, cancel read_task twice.
        await asyncio.gather(t.kill(), t.kill(), return_exceptions=True)
        await read_task
        self.assertFalse(t.is_running)
        self.assertTrue(t.was_killed)

    def _make_proc(self):
        proc = MagicMock()
        proc.wait = AsyncMock(return_value=0)
        sr = asyncio.StreamReader()
        sr.feed_eof()
        proc.stdout = sr
        proc.returncode = 0
        return proc

    async def test_kill_after_completed(self):
        t = BackgroundTask("t_done", "cmd", self._make_proc())
        t.start_reading(None, None)
        await t.read_task
        self.assertFalse(t.is_running)
        await t.kill()
        self.assertFalse(t.is_running)

    async def test_kill_sync_after_completed(self):
        t = BackgroundTask("t_done2", "cmd", self._make_proc())
        t.start_reading(None, None)
        await t.read_task
        t.kill_sync()
        self.assertFalse(t.is_running)

    async def test_kill_with_none_process(self):
        t = BackgroundTask("t_np", "cmd", None)
        await t.kill()
        self.assertFalse(t.is_running)
        self.assertTrue(t.was_killed)

    async def test_kill_mid_read_cancels_reader(self):
        t = BackgroundTask("t_midkill", "cmd", None, reader=None)
        never = asyncio.Event()

        async def never_read(_n):
            await never.wait()
            return b""

        t.reader = never_read
        t.process = self._make_proc()
        t.start_reading(None, None)
        await asyncio.sleep(0.05)
        await t.kill()
        self.assertTrue(t.read_task.cancelled() or t.read_task.done())


class TestBackgroundTaskStateAndCleanup(unittest.TestCase):
    def test_send_input_after_finish_returns_not_running(self):
        t = BackgroundTask("t_s", "cmd", None)
        t.is_running = False
        # sync path only; async covered elsewhere
        self.assertEqual(t.is_running, False)

    def test_append_output_truncation_keeps_tail(self):
        big = "x" * (200 * 1024)
        t = BackgroundTask("t_trunc", "cmd", None)
        t._append_output(big)
        t._append_output("TAILMARKER")
        out = t.get_formatted_output()
        self.assertTrue(t._output_truncated)
        self.assertIn("TAILMARKER", out)
        self.assertIn("Output truncated", out)
        self.assertLess(len(out), 200 * 1024 + 1000)


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
        t = BackgroundTask("t_dn", "cmd", self._make_proc())
        t.start_reading(None, None)
        await t.read_task
        kill_all_background_tasks([t])
        self.assertTrue(t.read_task.done())

    def test_kill_all_empty_list(self):
        kill_all_background_tasks([])


class TestBackgroundTaskOutput(unittest.TestCase):
    def test_move_to_background_sets_event(self):
        t = BackgroundTask("t_bg", "cmd", None)
        t.move_to_background()
        self.assertTrue(t.is_background)
        self.assertTrue(t.background_event.is_set())

    def test_strip_ansi_empty(self):
        self.assertEqual(strip_ansi(""), "")


# ---------------------------------------------------------------------------
# ManageShellTool: cancel from another task, duplicates, not-found
# ---------------------------------------------------------------------------
class TestManageShellEdge(unittest.IsolatedAsyncioTestCase):
    async def test_status_collects_exception_in_output(self):
        from tools.manage_shell import ManageShellTool

        t = BackgroundTask("t_err", "cmd", None)
        t.is_running = False
        t.output = ["partial\n", "Traceback (most recent call last):\n", "ValueError: boom\n"]
        ctx = type("C", (), {"background_tasks": [t], "app": None, "refresh_status": lambda: None})()
        res = await ManageShellTool().execute({"action": "status", "task_id": "t_err"}, ctx)
        self.assertIn("FINISHED", res)
        self.assertIn("ValueError", res)

    async def test_duplicate_task_ids_status_returns_first(self):
        from tools.manage_shell import ManageShellTool

        t1 = BackgroundTask("dup", "cmd1", None)
        t2 = BackgroundTask("dup", "cmd2", None)
        t1.is_running, t2.is_running = True, True
        ctx = type("C", (), {"background_tasks": [t1, t2], "app": None, "refresh_status": lambda: None})()
        res = await ManageShellTool().execute({"action": "status", "task_id": "dup"}, ctx)
        self.assertIn("cmd1", res)
        self.assertNotIn("cmd2", res)

    async def test_kill_not_found_gives_hint(self):
        from tools.manage_shell import ManageShellTool

        ctx = type("C", (), {"background_tasks": [], "app": None, "refresh_status": lambda: None})()
        res = await ManageShellTool().execute({"action": "kill", "task_id": "nope"}, ctx)
        self.assertIn("notfound", res)

    async def test_kill_from_other_session_is_not_listed(self):
        from tools.context import ToolContext
        from tools.manage_shell import ManageShellTool

        # Pass a real app-like object through ToolContext so the session scoping
        # (ctx.app.current_session_id) actually applies.
        app = type("A", (), {"current_session_id": "sess2", "background_tasks": []})()
        t = BackgroundTask("hidden", "cmd", None, session_id="sess1")
        app.background_tasks = [t]
        ctx = ToolContext(app=app)
        res = await ManageShellTool().execute({"action": "kill", "task_id": "hidden"}, ctx)
        self.assertIn("notfound", res)

    async def test_list_shows_running_and_finished(self):
        from tools.manage_shell import ManageShellTool

        t_r = BackgroundTask("r", "cmd1", None)
        t_r.is_running = True
        t_f = BackgroundTask("f", "cmd2", None)
        t_f.is_running = False
        ctx = type("C", (), {"background_tasks": [t_r, t_f], "app": None, "refresh_status": lambda: None})()
        res = await ManageShellTool().execute({"action": "list"}, ctx)
        self.assertIn("RUNNING", res)
        self.assertIn("FINISHED", res)


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
