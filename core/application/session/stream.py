"""Subagent streaming helpers operating on the unified AgentSession model.

Subagent sessions are AgentSession records (kind="subagent") stored per-project
under sessions/<parent_id>.subagents/ via SessionStore.
"""

import asyncio
import logging
from typing import Any, Callable, Optional

from core.domain.defaults.errors import ToolResult, parse_stream_step, parse_tool_result_step
from core.domain.entities.session import AgentSession, SessionStatus

logger = logging.getLogger(__name__)


def sync_session_metrics(session: AgentSession, agent: Any) -> None:
    """Copy token/cost metrics from the live agent onto its session record."""
    for attr in ("tokens_input", "tokens_output", "total_tokens", "cost_usd", "last_context_tokens"):
        setattr(session, attr, getattr(agent, attr, getattr(session, attr)))


_sync_subagent_metrics = sync_session_metrics


def record_session_step(step: tuple, session: AgentSession, text_accumulator: list) -> None:
    """Records an agent execution step into the session in canonical message format.

    Raw stream events (thinking_start/delta/end, bot_delta/text,
    tool_result) are canonicalized here into shared types (thinking/bot/tool)
    before being appended via AgentSession.add_event.
    """
    import math

    parsed = parse_stream_step(step)
    if parsed is None:
        return
    etype = parsed.event_type
    val1 = parsed.val1
    val2 = parsed.val2
    val3 = parsed.val3

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
    elif etype == "queued_user_message":
        text_accumulator[0] = ""
        session.add_event({"type": "user", "text": val1})
    elif etype == "event_divider":
        session.add_event({"type": "event_divider", "text": val1 or "Session Compacted"})
    elif etype == "error":
        session.add_event({"type": "error", "text": val1 or "Error"})


record_subagent_step = record_session_step


def configure_subagent_agent(
    subagent: Any,
    role_key: str,
    app: Any = None,
    project_dir: Optional[str] = None,
    worktree_branch: Optional[str] = None,
) -> Any:
    """Configures a subagent agent: binds the app, marks it as a subagent, and
    applies its role (system prompt, model, tool filtering).

    Shared by invoke_subagent spawn and manage_subagent follow-ups so the setup
    stays identical (and survives process restarts in the follow-up path).
    """
    subagent.app = app
    subagent.is_subagent = True
    from core.infrastructure.config.settings import get_settings

    subagent.auto_compact_token_limit = get_settings().subagents.auto_compact_token_limit
    if worktree_branch:
        subagent.worktree_branch = worktree_branch
    if app and hasattr(app, "sandbox_enabled"):
        subagent.sandbox_enabled = app.sandbox_enabled
    from core.roles import apply_role

    return apply_role(subagent, role_key, project_dir=project_dir, worktree_branch=worktree_branch)



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


async def _safe_save(store: Any, session: AgentSession) -> None:
    """Persist a session, logging and re-raising on storage failure.

    A silent swallow meant a failed save still marked the subagent COMPLETED,
    losing the session on disk. Now the failure is fully logged and propagated
    so callers can flip the status away from success; caller that chooses to
    contain the error may catch it explicitly.
    """
    try:
        await asyncio.to_thread(store.save, session)
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
    last_api_error = [None]
    try:
        async for step in subagent.stream_steps(message):
            if step and (
                step[0] == "error"
                or (step[0] == "event_divider" and len(step) > 1 and str(step[1]).startswith("API Error:"))
            ):
                last_api_error[0] = str(step[1])
            record_subagent_step(step, session, acc)
        _sync_subagent_metrics(session, subagent)
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
        acc[0] = "[Subagent cancelled]"
        _sync_subagent_metrics(session, subagent)
        if (
            hasattr(session, "messages")
            and session.messages
            and session.messages[-1].get("type") == "tool"
            and "result_text" not in session.messages[-1]
        ):
            session.add_event({
                "type": "tool",
                "result_text": "[interrupted | tool cancelled]",
                "status": "cancelled",
            })
        try:
            session.add_event({"type": "event_divider", "text": "Response Interrupted"})
        except Exception:
            pass
        session.finish(SessionStatus.CANCELLED, "Cancelled by user")
        try:
            await _safe_save(store, session)
        except Exception as err:
            acc[0] = f"[{error_prefix}: failed to save cancelled session: {err}]"
    except Exception as err:
        # Covers stream errors AND a failed post-completion save (propagated by
        # _safe_save). A failure to persist must not leave a COMPLETED status.
        acc[0] = f"[{error_prefix}: {err}]"
        _sync_subagent_metrics(session, subagent)
        session.finish(SessionStatus.ERROR, str(err))
        try:
            await _safe_save(store, session)
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
    subagent.session = session
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
                session.status = SessionStatus.RUNNING
                session.add_event({"type": "user", "text": message})
                session.add_event({"type": "status_change", "status": SessionStatus.RUNNING})
                continue
            break
    finally:
        if cleanup_fn:
            try:
                if asyncio.iscoroutinefunction(cleanup_fn):
                    await cleanup_fn(acc)
                else:
                    await asyncio.to_thread(cleanup_fn, acc)
            except Exception:
                pass
        merge_subagent_metrics(subagent, ctx)
        ctx.refresh_status()
        ctx.mark_subagent_status(session_id or session.id, session.status, acc[0])

        if notification_template:
            sid = session_id or session.id
            is_cancelled = str(getattr(session, "status", "")).lower() == "cancelled"
            if truncate_result:
                from core.infrastructure.tasks.output import truncate_subagent_result

                base_text = truncate_subagent_result(acc[0], sid)
            else:
                base_text = acc[0].strip()

            if is_cancelled:
                result_text = f"{base_text}\n\n[Subagent cancelled by user]" if base_text else "[Subagent cancelled by user]"
            else:
                result_text = base_text or "Completed with no text output."

            from core.domain.policies.messages import _xml_escape

            msg = notification_template.format(
                session_id=_xml_escape(sid),
                result_text=_xml_escape(result_text),
                title=_xml_escape(session.title or ""),
                description=_xml_escape(session.title or ""),
            )
            ctx.trigger_ai_response(msg)

    return acc[0]


def cancel_running_subagents(store: Any, parent_id: Optional[str] = None) -> int:
    """Cancels running subagent asyncio tasks and marks their sessions cancelled.

    Subagent sessions are the single source of truth for running state, so
    cancellation lives here instead of a parallel in-memory task registry.
    """
    if parent_id:
        sessions = store.children(parent_id)
    else:
        sessions = store.list(kind="subagent")

    cancelled = 0
    for sess in sessions:
        if getattr(sess, "status", "") != SessionStatus.RUNNING:
            continue
        async_task = getattr(sess, "async_task", None)
        if async_task and not async_task.done():
            try:
                async_task.cancel()
            except Exception:
                pass
        sess.finish(SessionStatus.CANCELLED, "Cancelled")
        store.save(sess)
        cancelled += 1
    return cancelled


async def send_subagent_followup(
    session: AgentSession,
    message: str,
    ctx: Any,
    store: Any,
) -> ToolResult:
    """Send a follow-up message to an existing subagent session.

    Resumes in the background; queues the message if the subagent is already busy.
    """
    if not message:
        return ToolResult.error("params", name="message", detail="required for 'send_message'")

    # Mirror the main agent's semantics: a follow-up can be sent in any
    # status. If the subagent is currently busy (live async_task), the
    # message is queued and drained by the running stream; otherwise it
    # starts immediately.
    if session.async_task and hasattr(session.async_task, "done") and not session.async_task.done():
        if not hasattr(session, "pending_messages"):
            session.pending_messages = []
        session.pending_messages.append(message)
        from core.infrastructure.runtime.subagent_tracker import _mark_subagent_running

        _mark_subagent_running(ctx.host, session.id, text=f"follow-up queued for {session.id}")
        return ToolResult.done(f"[queued | id {session.id}]")

    try:
        subagent = session.agent
        if not subagent:
            subagent = ctx.create_agent()
            if subagent:
                hist = session.agent_history
                if hist:
                    subagent.history = hist
                # Restore role behavior (system prompt, model, tool filtering)
                # so follow-ups match the original spawn, even after restart.
                configure_subagent_agent(
                    subagent,
                    session.role,
                    app=ctx.host,
                    project_dir=getattr(ctx, "project_dir", None) or session.project_dir,
                )
        elif getattr(ctx, "host", None):
            # Keep existing subagent provider credentials current with any host changes
            from core.roles.provider import rebind_provider

            pkey = getattr(subagent, "provider_key", "")
            if not pkey and hasattr(ctx.host, "pm") and hasattr(ctx.host.pm, "get_active_provider_key"):
                pkey = ctx.host.pm.get_active_provider_key()
            if pkey and isinstance(pkey, str):
                try:
                    rebind_provider(subagent, pkey)
                except Exception:
                    pass

        # Restore the isolated worktree context for follow-up so the subagent
        # keeps working on its own branch/cwd instead of silently falling back
        # to the parent checkout (worktree is removed on completion).
        if subagent and session.project_dir and session.branch_name:
            from core.infrastructure.runtime.subagent_worktree import SubagentWorktreeManager

            project_dir = await SubagentWorktreeManager.ensure_worktree_available_async(
                session, parent_dir=ctx.project_dir
            )
            subagent.project_dir = project_dir
            subagent.cwd = project_dir
            subagent.worktree_branch = session.branch_name

        if not subagent:
            return ToolResult.error("context", name=session.id, detail="no active agent")

        session.status = SessionStatus.RUNNING
        session.agent = subagent
        subagent.session = session
        session.add_event({"type": "user", "text": message})
        session.add_event({"type": "status_change", "status": SessionStatus.RUNNING})

        from core.domain.policies.messages import format_background_notification
        from core.infrastructure.runtime.subagent_tracker import _mark_subagent_running
        from core.infrastructure.runtime.subagent_worktree import SubagentWorktreeManager

        cleanup_fn = SubagentWorktreeManager.make_worktree_cleanup_fn(
            ctx.project_dir, session.project_dir, session.branch_name, is_followup=True
        )

        notification_hdr = format_background_notification(
            "subagent",
            session.title,
            session.id,
            "{result_text}",
            status="completed",
        )

        # The stream drains session.pending_messages inline, so only the
        # first (this) message is passed; queued follow-ups are consumed
        # by the loop until empty, keeping session running.
        bg_task = asyncio.create_task(
            run_subagent_stream_bg(
                subagent,
                message,
                session,
                ctx,
                store,
                cleanup_fn=cleanup_fn,
                error_prefix="Subagent message error",
                notification_template=notification_hdr,
                session_id=session.id,
                truncate_result=True,
            )
        )
        session.async_task = bg_task

        _mark_subagent_running(ctx.host, session.id, text=f"follow-up sent to {session.id}")
        return ToolResult.done(f"[message sent | id {session.id}]")
    except Exception as err:
        session.finish(SessionStatus.ERROR, str(err))
        store.save(session)
        return ToolResult.error("subagent_setup", detail=str(err), name=session.id)
