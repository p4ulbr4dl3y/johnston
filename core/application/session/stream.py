"""Subagent streaming helpers operating on the unified AgentSession model.

Subagent sessions are AgentSession records (kind="subagent") stored per-project
under sessions/<parent_id>.subagents/ via SessionStore.
"""

import asyncio
import logging
from typing import Any, Callable, Optional

from core.domain.defaults.errors import parse_tool_result_step
from core.domain.entities.session import STATUS_CANCELLED, STATUS_COMPLETED, STATUS_ERROR, SUBAGENT_STATUS_RUNNING
from core.session_manager import AgentSession


def record_subagent_step(step: tuple, session: AgentSession, text_accumulator: list) -> None:
    """Records a subagent execution step into the session in canonical message format.

    Raw stream events (thinking_start/delta/end, bot_delta/text,
    tool_result) are canonicalized here into shared types (thinking/bot/tool)
    before being appended via AgentSession.add_event.
    """
    import math

    if not step:
        return
    etype = step[0]
    val1 = step[1] if len(step) > 1 else ""
    val2 = step[2] if len(step) > 2 else ""
    val3 = step[3] if len(step) > 3 else None

    if etype == "thinking_start":
        session.add_event({"type": "thinking", "text": val1})
    elif etype == "thinking_delta":
        session.add_event({"type": "thinking", "text": val1})
    elif etype == "thinking_end":
        try:
            dur = float(val1)
            if not math.isfinite(dur):
                dur = 0.0
        except (ValueError, TypeError):
            dur = 0.0
        session.add_event({"type": "thinking", "text": val2, "duration": dur})
    elif etype == "thinking":
        # Informational thinking (auto-compaction/retry notices): always final.
        session.add_event({"type": "thinking", "text": val1, "duration": 0.0})
    elif etype == "tool":
        text_accumulator[0] = ""
        targs = val3 if isinstance(val3, dict) else {}
        session.add_event({"type": "tool", "tool_type": val1, "target": val2, "args": targs})
    elif etype == "tool_result":
        parsed = parse_tool_result_step(step)
        event = {"type": "tool", "result_text": val1 or parsed.content}
        if parsed.status is not None:
            event["status"] = parsed.status.value
        if parsed.is_error:
            event["is_error"] = True
        if parsed.returncode is not None:
            event["returncode"] = parsed.returncode
        session.add_event(event)
    elif etype == "bot_delta":
        text_accumulator[0] = text_accumulator[0] + val1
        session.add_event({"type": "bot", "text": text_accumulator[0]})
    elif etype == "bot_reset":
        text_accumulator[0] = ""
        session.add_event({"type": "bot_reset"})
    elif etype in ("bot_text", "outro"):
        text_accumulator[0] = val1
        session.add_event({"type": "bot", "text": text_accumulator[0], "final": True})
    elif etype == "event_divider":
        session.add_event({"type": "event_divider", "text": val1 or "Session Compacted"})


def configure_subagent_agent(subagent: Any, role_key: str, app: Any = None, project_dir: Optional[str] = None) -> Any:
    """Configures a subagent agent: binds the app, marks it as a subagent, and
    applies its role (system prompt, model, tool filtering).

    Shared by invoke_subagent spawn and manage_subagent follow-ups so the setup
    stays identical (and survives process restarts in the follow-up path).
    """
    subagent.app = app
    subagent.is_subagent = True
    return apply_subagent_role(subagent, role_key, project_dir=project_dir)


def apply_subagent_role(subagent: Any, role_key: str, project_dir: Optional[str] = None) -> Any:
    """Applies a role definition to a subagent agent.

    Thin facade delegating to the decomposed core.roles package (resolution,
    provider switching, tool filtering, prompt/model wiring). Kept as the
    public entry point used by invoke_subagent and manage_subagent follow-ups.
    """
    from core.roles import apply_role

    return apply_role(subagent, role_key, project_dir=project_dir)


def merge_subagent_metrics(subagent: Any, context: Any) -> None:
    """Merges token consumption and cost metrics from subagent into parent app agent."""

    def _val(obj: Any, attr: str, default: Any = 0) -> Any:
        v = getattr(obj, attr, default)
        if isinstance(v, (int, float)) and not isinstance(v, bool):
            return v
        return default

    if context.host and getattr(context.host, "agent", None):
        main_agent = context.host.agent
        last_in = _val(subagent, "_merged_tokens_input", 0)
        last_out = _val(subagent, "_merged_tokens_output", 0)
        last_tot = _val(subagent, "_merged_total_tokens", 0)
        last_cost = _val(subagent, "_merged_cost_usd", 0.0)

        cur_in = _val(subagent, "tokens_input", 0)
        cur_out = _val(subagent, "tokens_output", 0)
        cur_tot = _val(subagent, "total_tokens", 0)
        cur_cost = _val(subagent, "cost_usd", 0.0)

        delta_in = cur_in - last_in
        delta_out = cur_out - last_out
        delta_tot = cur_tot - last_tot
        delta_cost = cur_cost - last_cost

        if delta_in > 0:
            main_agent.tokens_input = _val(main_agent, "tokens_input", 0) + delta_in
        if delta_out > 0:
            main_agent.tokens_output = _val(main_agent, "tokens_output", 0) + delta_out
        if delta_tot > 0:
            main_agent.total_tokens = _val(main_agent, "total_tokens", 0) + delta_tot
        if delta_cost > 0:
            main_agent.cost_usd = _val(main_agent, "cost_usd", 0.0) + delta_cost

        subagent._merged_tokens_input = cur_in
        subagent._merged_tokens_output = cur_out
        subagent._merged_total_tokens = cur_tot
        subagent._merged_cost_usd = cur_cost


logger = logging.getLogger(__name__)


def _safe_save(store: Any, session: AgentSession) -> None:
    """Persist a session, logging and re-raising on storage failure.

    A silent swallow meant a failed save still marked the subagent COMPLETED,
    losing the session on disk. Now the failure is fully logged and propagated
    so callers can flip the status away from success; caller that chooses to
    contain the error may catch it explicitly.
    """
    try:
        store.save(session)
    except Exception:
        logger.exception("Failed to save subagent session %s", session.id)
        raise


async def _run_single_subagent_message(
    subagent: Any,
    message: str,
    session: AgentSession,
    ctx: Any,
    store: Any,
    error_prefix: str = "Subagent error",
) -> str:
    """Runs a single subagent message stream, recording steps and finishing the session.

    Returns the accumulated text and handles success/cancel/error transitions,
    persisting the session in each terminal state.
    """
    acc = [""]
    try:
        async for step in subagent.stream_steps(message):
            record_subagent_step(step, session, acc)
        session.tokens_input = getattr(subagent, "tokens_input", session.tokens_input)
        session.tokens_output = getattr(subagent, "tokens_output", session.tokens_output)
        session.total_tokens = getattr(subagent, "total_tokens", session.total_tokens)
        session.cost_usd = getattr(subagent, "cost_usd", session.cost_usd)
        session.last_context_tokens = getattr(subagent, "last_context_tokens", session.last_context_tokens)
        session.finish(STATUS_COMPLETED)
        _safe_save(store, session)
    except asyncio.CancelledError:
        acc[0] = "[Subagent cancelled]"
        session.tokens_input = getattr(subagent, "tokens_input", session.tokens_input)
        session.tokens_output = getattr(subagent, "tokens_output", session.tokens_output)
        session.total_tokens = getattr(subagent, "total_tokens", session.total_tokens)
        session.cost_usd = getattr(subagent, "cost_usd", session.cost_usd)
        session.last_context_tokens = getattr(subagent, "last_context_tokens", session.last_context_tokens)
        session.finish(STATUS_CANCELLED, "Cancelled by user")
        try:
            _safe_save(store, session)
        except Exception as err:
            acc[0] = f"[{error_prefix}: failed to save cancelled session: {err}]"
    except Exception as err:
        # Covers stream errors AND a failed post-completion save (propagated by
        # _safe_save). A failure to persist must not leave a COMPLETED status.
        acc[0] = f"[{error_prefix}: {err}]"
        session.tokens_input = getattr(subagent, "tokens_input", session.tokens_input)
        session.tokens_output = getattr(subagent, "tokens_output", session.tokens_output)
        session.total_tokens = getattr(subagent, "total_tokens", session.total_tokens)
        session.cost_usd = getattr(subagent, "cost_usd", session.cost_usd)
        session.last_context_tokens = getattr(subagent, "last_context_tokens", session.last_context_tokens)
        session.finish(STATUS_ERROR, str(err))
        try:
            _safe_save(store, session)
        except Exception:
            pass
    return acc[0]


async def run_subagent_stream_bg(
    subagent: Any,
    prompt_or_message: str,
    session: AgentSession,
    ctx: Any,
    store: Any,
    cleanup_fn: Optional[Callable[[list], None]] = None,
    error_prefix: str = "Subagent error",
    notification_template: str = "",
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
    acc = [""]
    try:
        message = prompt_or_message
        while True:
            acc[0] = await _run_single_subagent_message(
                subagent, message, session, ctx, store, error_prefix=error_prefix
            )

            # Drain follow-up messages queued while the previous message ran.
            if session.pending_messages:
                message = session.pending_messages.pop(0)
                session.status = SUBAGENT_STATUS_RUNNING
                session.add_event({"type": "status_change", "status": SUBAGENT_STATUS_RUNNING})
                continue
            break
    finally:
        if cleanup_fn:
            try:
                cleanup_fn(acc)
            except Exception:
                pass
        merge_subagent_metrics(subagent, ctx)
        ctx.refresh_status()
        ctx.mark_subagent_status(session_id or session.id, session.status, acc[0])

        if notification_template:
            sid = session_id or session.id
            if truncate_result:
                from core.infrastructure.tasks.output import truncate_subagent_result

                result_text = truncate_subagent_result(acc[0], sid) or "Completed with no text output."
            else:
                result_text = acc[0].strip() or "Completed with no text output."

            msg = notification_template.format(
                session_id=sid,
                result_text=result_text,
                description=session.description,
            )
            ctx.trigger_ai_response(msg)

    return acc[0]


def cancel_running_subagents(store: Any, parent_id: Optional[str] = None) -> int:
    """Cancels running subagent asyncio tasks and marks their sessions cancelled.

    Subagent sessions are the single source of truth for running state, so
    cancellation lives here instead of a parallel in-memory task registry.
    """
    if parent_id:
        sessions = store.get_subagents_for_parent(parent_id)
    else:
        sessions = store.list(kind="subagent")

    cancelled = 0
    for sess in sessions:
        if getattr(sess, "status", "") != SUBAGENT_STATUS_RUNNING:
            continue
        async_task = getattr(sess, "async_task", None)
        if async_task and not async_task.done():
            try:
                async_task.cancel()
            except Exception:
                pass
        sess.finish(STATUS_CANCELLED, "Cancelled")
        store.save(sess)
        cancelled += 1
    return cancelled
