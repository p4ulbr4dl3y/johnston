"""Helpers for fire-and-forget asyncio background tasks.

``asyncio`` only keeps weak references to running tasks: a bare
``asyncio.get_running_loop().create_task(...)`` whose result is dropped can be
garbage-collected before it finishes. :func:`spawn_background_task` holds a
strong reference until the task completes, so fire-and-forget work (background
model refreshes and similar) can never silently vanish.
"""

import asyncio
import logging
from typing import Any, Coroutine, Optional, Set

logger = logging.getLogger(__name__)

_background_tasks: Set["asyncio.Task[Any]"] = set()


def spawn_background_task(coro: "Coroutine[Any, Any, Any]") -> Optional["asyncio.Task[Any]"]:
    """Schedule *coro* as a strongly-referenced background task.

    Returns the task, or ``None`` when no event loop is running (the coroutine
    is closed instead of being left to trigger 'never awaited' warnings).
    Exceptions are logged rather than raised: callers treat this as set-and-
    forget by contract.
    """
    try:
        task = asyncio.get_running_loop().create_task(coro)
    except RuntimeError:
        coro.close()
        return None

    _background_tasks.add(task)

    def _on_done(done: "asyncio.Task[Any]") -> None:
        _background_tasks.discard(done)
        if not done.cancelled():
            exc = done.exception()
            if exc is not None:
                logger.warning("Background task failed: %s", exc, exc_info=exc)

    task.add_done_callback(_on_done)
    return task
