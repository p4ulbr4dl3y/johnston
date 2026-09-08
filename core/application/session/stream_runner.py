"""Execution of subagent stream turns and background stream runs."""

import asyncio
import logging
from typing import Any, Callable, Optional

from core.application.session.stream_agent import merge_subagent_metrics, sync_session_metrics
from core.application.session.stream_steps import record_session_step
from core.domain.entities.session import AgentSession, SessionStatus
from core.infrastructure.runtime.session_interruption import record_session_interruption

logger = logging.getLogger(__name__)


async def _safe_save(store: Any, session: AgentSession) -> None:
    """Persist a session, logging and re-raising on storage failure.

    A raised ``asyncio.CancelledError`` (save step interrupted mid-teardown)
    must propagate unpolluted so a task cancelled during teardown stays
    cancelled instead of dying with a secondary RuntimeError/OSError.
    """
    if store is None:
        return
    try:
        await asyncio.to_thread(store.save, session)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Failed to save subagent session %s", session.id)
        raise


def _is_real_cancellation() -> bool:
    """True when the current task was cancelled via ``task.cancel()`` rather
    than by a CancelledError raised from the coroutine itself.

    asyncio (3.11+) tracks pending cancellations with ``Task.cancelling()``:
    while a CancelledError handler runs, a real cancellation still has count
    > 0 and will NOT be re-delivered automatically once the handler returns —
    re-raising is what keeps the task actually cancelled. On 3.10 (no
    ``cancelling()`` API) the delivered cancellation has already cleared
    ``_must_cancel``, so this returns False and the pre-existing graceful
    conversion behavior is preserved.
    """
    task = asyncio.current_task()
    if task is None:
        return False
    cancelling = getattr(task, "cancelling", None)
    if cancelling is not None:
        return task.cancelling() > 0
    return False


async def execute_session_turn(
    agent: Any,
    message: str,
    session: AgentSession,
    store: Any,
    *,
    error_prefix: str = "Execution error",
    cancel_message: Optional[str] = None,
    step_callback: Optional[Callable[[tuple, AgentSession, list], None]] = None,
) -> str:
    """Runs a single agent message stream, recording steps into session and finishing the session.

    Returns accumulated text and handles success/cancel/error transitions,
    persisting the session in each terminal state.
    """
    acc = [""]
    last_api_error = [None]
    is_sub = getattr(agent, "is_subagent", False)
    cancelled_text = cancel_message or ("[Subagent cancelled]" if is_sub else "[Session cancelled]")
    err_prefix = error_prefix or ("Subagent error" if is_sub else "Error")

    try:
        async for step in agent.stream_steps(message):
            if step and step[0] == "error":
                last_api_error[0] = str(step[1]) if len(step) > 1 else "Error"
            record_session_step(step, session, acc)
            if step_callback:
                step_callback(step, session, acc)
        sync_session_metrics(session, agent)
        if last_api_error[0]:
            if not acc[0].strip():
                acc[0] = f"[{last_api_error[0]}]"
            else:
                acc[0] = f"{acc[0]}\n\n[{last_api_error[0]}]"
            session.finish(SessionStatus.ERROR, last_api_error[0])
        else:
            session.finish(SessionStatus.COMPLETED)
        await _safe_save(store, session)
    except asyncio.CancelledError:
        acc[0] = cancelled_text
        sync_session_metrics(session, agent)
        record_session_interruption(session, "Response Interrupted")
        session.finish(SessionStatus.CANCELLED, "Cancelled by user")
        try:
            await _safe_save(store, session)
        except asyncio.CancelledError:
            raise  # never swallow the pending cancellation
        except Exception as err:
            # Failures may not replace a pending task cancellation (audit A7):
            # re-raise as a CancelledError so the task ends cancelled, keeping
            # the save failure note for diagnostics.
            if _is_real_cancellation():
                raise asyncio.CancelledError(
                    f"[{err_prefix}: failed to save cancelled session: {err}]"
                ) from err
            acc[0] = f"[{err_prefix}: failed to save cancelled session: {err}]"
    except Exception as err:
        acc[0] = f"[{err_prefix}: {err}]"
        sync_session_metrics(session, agent)
        record_session_interruption(session, "Response Interrupted")
        session.finish(SessionStatus.ERROR, str(err))
        try:
            await _safe_save(store, session)
        except Exception:
            pass
    return acc[0]


async def _run_single_subagent_message(
    subagent: Any,
    message: str,
    session: AgentSession,
    ctx: Any = None,
    store: Any = None,
    error_prefix: str = "Subagent error",
) -> str:
    """Runs a single subagent message stream, recording steps and finishing the session."""
    return await execute_session_turn(
        subagent,
        message,
        session,
        store,
        error_prefix=error_prefix,
        cancel_message="[Subagent cancelled]",
    )


async def run_subagent_stream_bg(
    subagent: Any,
    prompt_or_message: str,
    session: AgentSession,
    ctx: Any,
    store: Any,
    cleanup_fn: Optional[Callable[[list], None]] = None,
    error_prefix: str = "Subagent error",
    notification_template: bool | str = True,
    session_id: Optional[str] = None,
    truncate_result: bool = False,
) -> str:
    """Executes a subagent step stream in background with error handling, session finish, cleanup, and UI notifications.

    Mirrors the main agent's message-queue semantic: a follow-up message sent
    while the subagent is busy is queued on `session.pending_messages` and
    drained here after the current message finishes, so the subagent keeps
    processing until its queue is empty. The session stays `running` while the
    queue is non-empty and only finishes `completed` once drained.
    """
    subagent.session = session
    acc = [""]
    try:
        message = prompt_or_message
        while True:
            acc[0] = await _run_single_subagent_message(
                subagent, message, session, ctx, store, error_prefix=error_prefix
            )

            if session.status in (SessionStatus.CANCELLED, SessionStatus.ERROR, "cancelled", "error"):
                if getattr(session, "pending_messages", None):
                    session.pending_messages.clear()
                break

            # Drain follow-up messages queued while the previous message ran.
            if session.pending_messages:
                message = session.pending_messages.pop(0)
                session.status = SessionStatus.RUNNING
                session.add_event({"type": "user", "text": message})
                session.add_event({"type": "status_change", "status": SessionStatus.RUNNING})
                continue
            break
    finally:
        # A7 shutdown-failure shield: a task cancelled mid-teardown must stay
        # cancelled. Every fallible cleanup/store/UI step is guarded with a
        # narrow `except Exception: pass` (which never swallows
        # asyncio.CancelledError on Py3.8+), and the top-level guard re-raises
        # a CancelledError occurring during the finally itself, so teardown
        # failures can never replace the pending cancellation.
        try:
            if cleanup_fn:
                try:
                    if asyncio.iscoroutinefunction(cleanup_fn):
                        await cleanup_fn(acc)
                    else:
                        await asyncio.to_thread(cleanup_fn, acc)
                except Exception:
                    pass
            try:
                merge_subagent_metrics(subagent, ctx)
            except Exception:
                pass
            try:
                ctx.refresh_status()
            except Exception:
                pass

            # A cancelled run must not re-enter the main chat (audit A2):
            # /new cancels the child via task.cancel(); streaming a completion
            # notification (or a toolcard status repaint) into a fresh session
            # would echo the old run's message into the new chat.
            if session.status in (SessionStatus.CANCELLED, "cancelled"):
                setattr(session, "suppress_notification", True)

            is_suppressed = getattr(session, "suppress_notification", False)

            # Prevent cross-session leaks: if the UI switched active sessions,
            # do not inject notifications or repaints into the fresh session.
            curr_sid = getattr(getattr(ctx, "host", None), "current_session_id", None)
            session_switched = (
                curr_sid is not None
                and getattr(session, "parent_id", None)
                and curr_sid != session.parent_id
            )

            if not is_suppressed and not session_switched:
                try:
                    ctx.mark_subagent_status(session_id or session.id, session.status, acc[0])
                except Exception:
                    pass

            if not is_suppressed and not session_switched:
                if notification_template:
                    try:
                        sid = session_id or session.id
                        sess_status = str(getattr(session, "status", "")).lower()
                        if "cancel" in sess_status:
                            status_val = "cancelled"
                        elif "error" in sess_status:
                            status_val = "error"
                        else:
                            status_val = "completed"

                        if truncate_result:
                            from core.infrastructure.tasks.output import truncate_subagent_result

                            base_text = truncate_subagent_result(acc[0], sid)
                        else:
                            base_text = acc[0].strip()

                        if status_val == "cancelled":
                            result_text = (
                                f"{base_text}\n\n[Subagent cancelled by user]"
                                if base_text
                                else "[Subagent cancelled by user]"
                            )
                        else:
                            result_text = base_text or "Completed with no text output."

                        branch = getattr(session, "branch_name", None) or None
                        if status_val == "completed":
                            if branch:
                                hint = f"\n\n[Next: inspect diff & 'git merge {branch}'. If incomplete/broken: call message_subagent(id=\"{sid}\", message=\"...\")]"
                            else:
                                hint = f"\n\n[If incomplete/fixes needed: call message_subagent(id=\"{sid}\", message=\"...\")]"
                            result_text += hint
                        elif status_val == "error":
                            result_text += f"\n\n[If fixable: call message_subagent(id=\"{sid}\", message=\"...\")]"

                        from core.domain.policies.messages import format_background_notification

                        msg = format_background_notification(
                            type_="subagent",
                            title=session.title or "Subagent",
                            task_id=sid,
                            result=result_text,
                            status=status_val,
                            branch=branch,
                        )
                        ctx.trigger_ai_response(msg)
                    except Exception:
                        pass
        except asyncio.CancelledError:
            raise
        finally:
            try:
                sid = session_id or getattr(session, "id", None)
                app = getattr(ctx, "host", None)
                if app is not None and sid and hasattr(app, "_subagent_tools") and isinstance(app._subagent_tools, dict):
                    app._subagent_tools.pop(sid, None)

                if hasattr(session, "async_task"):
                    session.async_task = None
                if hasattr(session, "agent"):
                    session.agent = None
                if hasattr(subagent, "session") and getattr(subagent, "session", None) is session:
                    subagent.session = None
            except Exception:
                pass

    return acc[0]


def cancel_running_subagents(store: Any, parent_id: Optional[str] = None) -> int:
    """Cancels running subagent asyncio tasks and marks their sessions cancelled."""
    from core.application.session.subagent_service import SubagentService

    return SubagentService.cancel_running_subagents(store, parent_id)
