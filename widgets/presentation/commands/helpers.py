"""Helper functions for command execution, task cancellation, and state resets."""
from __future__ import annotations

import asyncio


def cancel_active_workers(app) -> None:
    """Cancel any running Textual background workers on the app."""
    try:
        if hasattr(app, "workers"):
            for w in [w for w in app.workers if getattr(w, "is_running", False)]:
                w.cancel()
    except Exception:
        pass


async def cancel_active_workers_and_tasks(
    app,
    *,
    wait_workers: bool = False,
    timeout: float = 1.0,
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
            from core.application.session.stream import cancel_running_subagents

            cancel_running_subagents(app.sm, session_id)
        except Exception:
            pass


def reset_app_state(
    app,
    *,
    is_generating: bool = False,
    is_read_only: bool = False,
    clear_queue: bool = True,
    session_id: str | None = None,
    role: str | None = None,
) -> None:
    """Reset standard UI state flags and message queues."""
    app.is_generating = is_generating
    app.is_read_only = is_read_only
    if clear_queue and hasattr(app, "message_queue"):
        app.message_queue.clear()
    if session_id is not None:
        app.current_session_id = session_id
    if role is not None:
        app.role = role
