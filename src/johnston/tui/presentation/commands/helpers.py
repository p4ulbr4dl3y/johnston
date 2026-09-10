"""Helper functions for command execution, task cancellation, and state resets."""
from __future__ import annotations

import asyncio

# How long to wait for cancelled workers to finish teardown (e.g. the
# "Response Interrupted" divider) before commands re-render a session view.
WORKER_TEARDOWN_TIMEOUT = 2.0


def cancel_active_workers(app) -> None:
    """Cancel any running Textual background workers on the app.

    Also cancels the registered compaction task (``app._compact_task``): /compact
    runs in a plain ``asyncio.create_task`` (not a Textual worker), so Esc and
    command-level cancellation reach it only through this explicit hook.
    """
    try:
        if hasattr(app, "workers"):
            for w in [w for w in app.workers if getattr(w, "is_running", False)]:
                w.cancel()
    except Exception:
        pass
    try:
        compact_task = getattr(app, "_compact_task", None)
        if compact_task is not None and not compact_task.done():
            compact_task.cancel()
    except Exception:
        pass


async def await_workers_finished(app, timeout: float = WORKER_TEARDOWN_TIMEOUT) -> None:
    """Wait until cancelled workers have completed their cleanup.

    A cancelled generation worker still runs its finally/teardown (e.g. the
    "Response Interrupted" divider). Unless callers wait, that teardown can
    mount messages into a chat view the command just cleared for a session.
    """
    try:
        from textual.worker import WorkerCancelled, WorkerFailed

        for w in [w for w in getattr(app, "workers", []) if not getattr(w, "is_finished", True)]:
            try:
                await asyncio.wait_for(w.wait(), timeout=timeout)
            except (WorkerCancelled, WorkerFailed, TimeoutError, asyncio.TimeoutError):
                pass
    except Exception:
        pass


async def cancel_active_workers_and_tasks(
    app,
    *,
    wait_workers: bool = False,
    timeout: float = WORKER_TEARDOWN_TIMEOUT,
    kill_tasks: bool = True,
    cancel_subagents: bool = True,
    session_id: str | None = None,
) -> None:
    """Cancel workers, wait for cleanup if requested, and kill tasks/subagents."""
    cancel_active_workers(app)

    if wait_workers:
        try:
            from textual.worker import WorkerCancelled, WorkerFailed

            for w in [w for w in getattr(app, "workers", []) if not getattr(w, "is_finished", True)]:
                try:
                    await asyncio.wait_for(w.wait(), timeout=timeout)
                except (WorkerCancelled, WorkerFailed, TimeoutError, asyncio.TimeoutError):
                    pass
        except Exception:
            pass

    if kill_tasks and hasattr(app, "task_manager"):
        try:
            await app.task_manager.kill_all()
        except Exception:
            pass

    if cancel_subagents and getattr(app, "sm", None) is not None:
        try:
            from johnston.tui.adapters import core_bridge

            core_bridge.cancel_running_subagents(app.sm, session_id)
        except Exception:
            pass


def reset_app_state(
    app,
    *,
    is_generating: bool = False,
    is_compacting: bool = False,
    is_read_only: bool = False,
    clear_queue: bool = True,
    session_id: str | None = None,
    role: str | None = None,
    clear_pending_fork: bool = True,
) -> None:
    """Reset standard UI state flags and message queues."""
    app.is_generating = is_generating
    app._is_compacting = is_compacting
    app.is_compacting = is_compacting
    app.is_read_only = is_read_only
    if clear_pending_fork and hasattr(app, "pending_fork"):
        app.pending_fork = None
    if clear_queue and hasattr(app, "message_queue"):
        app.message_queue.clear()
    if session_id is not None:
        app.current_session_id = session_id
    if role is not None:
        app.role = role
    app.current_plan = None
    app.current_plan_explanation = ""
    if hasattr(app, "query_one"):
        try:
            from johnston.tui.presentation.widgets.plan_notch import PlanNotch

            app.query_one(PlanNotch).clear_plan()
        except Exception:
            pass
