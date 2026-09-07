"""Follow-up messages for existing subagent sessions."""

import asyncio
from typing import Any

from core.application.session.stream_agent import configure_subagent_agent
from core.application.session.stream_runner import _safe_save, run_subagent_stream_bg
from core.domain.defaults.errors import ToolResult
from core.domain.entities.session import AgentSession, SessionStatus


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
    setattr(session, "suppress_notification", False)
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
        if store:
            if hasattr(store, "_sessions") and isinstance(store._sessions, dict):
                store._sessions[session.id] = session
            await _safe_save(store, session)

        from core.infrastructure.runtime.subagent_tracker import _mark_subagent_running
        from core.infrastructure.runtime.subagent_worktree import SubagentWorktreeManager

        cleanup_fn = SubagentWorktreeManager.make_worktree_cleanup_fn(
            ctx.project_dir, session.project_dir, session.branch_name, is_followup=True
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
                notification_template=True,
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
