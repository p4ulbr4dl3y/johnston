"""Cooperative cancellation helpers for blocking tool work.

`asyncio.to_thread` does not stop the underlying thread when the awaiting
coroutine is cancelled: the caller returns immediately but the worker thread
keeps running to completion. For short-lived file I/O that is harmless, but for
long conversions (PDF/DOCX -> Markdown), image processing, or subprocess calls
the orphaned work can linger for seconds and waste CPU / keep a pipe open.

`run_cancellable` runs a sync callable in a worker thread and wires a per-call
`threading.Event` into the callable's `cancel_event` keyword argument (only
when the target actually accepts it, determined cheaply via a cached signature
inspection). If the caller is cancelled, the event is set (cooperative sync code
can bail out of long loops early) and `asyncio.CancelledError` is re-raised --
the caller is never blocked by orphaned work.

Workers that want to cooperate should accept an optional ``cancel_event``
argument and check ``cancel_event.is_set()`` in loops / before expensive steps.
Because the event is created per-call, a fresh worker is never pre-cancelled.
"""

import asyncio
import inspect
import threading
from typing import Any, Callable, TypeVar

T = TypeVar("T")

# Cache of (module, qualname) -> whether the callable accepts a cancel_event kwarg.
# inspect.signature is expensive relative to a plain call, so we memoize it.
_SUPPORTS_CACHE: dict = {}
_LOCK = threading.Lock()


def _accepts_cancel_event(func: Callable) -> bool:
    """Return True if ``func`` can receive a ``cancel_event`` keyword argument."""
    key = (getattr(func, "__module__", ""), getattr(func, "__qualname__", ""))
    with _LOCK:
        cached = _SUPPORTS_CACHE.get(key)
        if cached is not None:
            return cached
    try:
        accepted = "cancel_event" in inspect.signature(func).parameters
    except (TypeError, ValueError):
        accepted = False
    with _LOCK:
        _SUPPORTS_CACHE[key] = accepted
    return accepted


def new_cancel_event() -> threading.Event:
    """Create a fresh, unset cancellation event for one tool invocation."""
    return threading.Event()


async def run_cancellable(func: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run ``func`` in a worker thread with cooperative cancellation.

    Wires a per-call ``threading.Event`` into ``func``'s ``cancel_event`` kwarg
    (only if the target accepts it) and sets it when the caller is cancelled, so
    cooperative sync workers can abort long loops early. Returns the callable's
    return value on success and raises ``asyncio.CancelledError`` on
    cancellation (the caller is not blocked).
    """
    cancel_event = new_cancel_event()
    if _accepts_cancel_event(func):
        kwargs.setdefault("cancel_event", cancel_event)
    fut = asyncio.ensure_future(asyncio.to_thread(func, *args, **kwargs))
    try:
        return await fut
    except asyncio.CancelledError:
        cancel_event.set()
        raise
