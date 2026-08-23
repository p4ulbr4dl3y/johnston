"""Tests for the fire-and-forget background task helper."""

import asyncio

from core.infrastructure.runtime.background import _background_tasks, spawn_background_task


def test_spawn_without_running_loop_closes_coroutine():
    async def work():
        return 1

    coro = work()
    assert spawn_background_task(coro) is None
    # Closed instead of left dangling: no 'never awaited' warning path.
    assert coro.cr_await is None


def test_spawn_keeps_strong_reference_until_done():
    async def main():
        async def work():
            await asyncio.sleep(0)
            return 42

        task = spawn_background_task(work())
        assert task is not None
        assert task in _background_tasks  # strong ref held while running
        assert await task == 42
        assert task not in _background_tasks  # discarded after completion

    asyncio.run(main())


def test_spawn_logs_exception_instead_of_raising(caplog):
    import logging

    async def main():
        async def boom():
            raise RuntimeError("kaboom")

        task = spawn_background_task(boom())
        assert task is not None
        with caplog.at_level(logging.WARNING):
            try:
                await task
            except RuntimeError:
                pass

    asyncio.run(main())
    assert any("kaboom" in rec.message for rec in caplog.records)
