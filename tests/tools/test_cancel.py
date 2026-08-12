"""Tests for cooperative cancellation helpers (tools.cancel)."""

import asyncio
import threading
import time
import unittest

from tools.cancel import new_cancel_event, run_cancellable


def _simple_blocking(seconds: float, cancel_event: threading.Event | None = None) -> str:
    """A cooperative worker that polls the cancel event in its loop."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        if cancel_event is not None and cancel_event.is_set():
            raise RuntimeError("cancelled cooperatively")
        time.sleep(0.01)
    return "done"


def _no_event_arg(seconds: float) -> str:
    """A worker that does NOT accept a cancel_event kwarg (must not break)."""
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        time.sleep(0.01)
    return "done-sync"


class TestRunCancellable(unittest.IsolatedAsyncioTestCase):
    async def test_runs_to_completion(self):
        self.assertEqual(await run_cancellable(_simple_blocking, 0.01), "done")

    async def test_no_event_arg_function_still_works(self):
        self.assertEqual(await run_cancellable(_no_event_arg, 0.01), "done-sync")

    async def test_cancellation_raises_cancelled_error_immediately(self):
        task = asyncio.create_task(run_cancellable(_simple_blocking, 5.0))
        await asyncio.sleep(0.05)
        start = time.monotonic()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        # The caller returns immediately, not waiting for the 5s worker.
        self.assertLess(time.monotonic() - start, 2.0)

    async def test_cancel_event_is_set_on_cancellation(self):
        seen = []

        def worker(cancel_event=None):
            end = time.monotonic() + 5.0
            while time.monotonic() < end:
                if cancel_event is not None and cancel_event.is_set():
                    seen.append(True)
                    return "bailed"
                time.sleep(0.01)
            return "done"

        task = asyncio.create_task(run_cancellable(worker))
        await asyncio.sleep(0.05)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        # Cooperative workers see the event flip and can react after cancellation.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            if seen:
                break
            await asyncio.sleep(0.01)
        self.assertTrue(seen)

    async def test_new_cancel_event_is_unset(self):
        evt = new_cancel_event()
        self.assertFalse(evt.is_set())
        evt.set()
        self.assertTrue(evt.is_set())


if __name__ == "__main__":
    unittest.main()
