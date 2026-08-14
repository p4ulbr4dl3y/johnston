import asyncio
from typing import Any, Dict

from core.session_manager import (
    STATUS_CANCELLED,
    STATUS_ERROR,
    SessionStore,
)
from tools.base import BaseTool, format_tool_error


class ManageSubagentTool(BaseTool):
    name = "manage_subagent"
    description = "Manage active and historical subagents: list, status, kill, send_message."
    schema = {
        "type": "function",
        "function": {
            "name": "manage_subagent",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {"type": "string", "enum": ["list", "status", "kill", "send_message"]},
                    "session_id": {"type": "string", "description": "Target subagent session_id"},
                    "message": {"type": "string", "description": "Follow-up message for subagent"},
                },
                "required": ["action"],
            },
        },
    }

    def _get_store(self, app: Any) -> SessionStore:
        if app and getattr(app, "sm", None):
            return app.sm
        return SessionStore.get_instance()

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> str:
        from tools.registry import normalize_tool_args

        args = normalize_tool_args("manage_subagent", args)
        ctx = self._ensure_context(ctx)
        action = (args.get("action") or "").strip().lower()
        session_id = (args.get("session_id") or "").strip()
        message = (args.get("message") or "").strip()

        store = self._get_store(ctx.app)

        curr_session_id = ctx.session_id

        if action == "list":
            show_all = bool(args.get("all", False))
            if show_all:
                target_sessions = store.list(kind="subagent")
            else:
                target_sessions = (
                    store.get_subagents_for_parent(curr_session_id) if curr_session_id else store.list(kind="subagent")
                )
            if not target_sessions:
                return "No subagent sessions found for current session."
            lines = ["Active/Past Subagent Sessions:"]
            for sess in target_sessions:
                lines.append(
                    f"• ID: {sess.id} | Status: {sess.status.upper()} | Type: {sess.role} | Description: {sess.description}"
                )
            return "\n".join(lines)

        if not session_id:
            return format_tool_error("params", name="session_id", detail=f"required for '{action}'")

        session = store.find_session_by_description_or_id(session_id, parent_id=curr_session_id)
        if not session:
            return format_tool_error("notfound", name=session_id)

        if action == "status":
            lines = [
                f"Subagent Status ({session.id}):",
                f"• Description: {session.description}",
                f"• Status: {session.status.upper()}",
                f"• Type: {session.role}",
            ]

            if session.status == "running":
                lines.append("\nRecent Events Log:")
                recent = session.messages[-15:]
                for evt in recent:
                    etype = evt.get("type")
                    if etype == "user":
                        lines.append(f"  [User]: {evt.get('text')}")
                    elif etype == "bot":
                        lines.append(f"  [Bot]: {evt.get('text')[:150]}...")
                    elif etype == "tool":
                        lines.append(f"  [Tool]: {evt.get('tool_type')} ({evt.get('target')})")
                    elif etype == "status_change":
                        lines.append(f"  [Status]: {evt.get('status')}")

                lines.append(
                    "\nNote: Subagent is still running. STOP calling manage_subagent(status) in a loop and end your turn now."
                )
            return "\n".join(lines)

        elif action == "kill":
            if session.status != "running":
                return f"{session.id} already in '{session.status}'"

            if session.async_task and not session.async_task.done():
                try:
                    session.async_task.cancel()
                except Exception:
                    pass

            session.finish(STATUS_CANCELLED, "Cancelled via manage_subagent tool")
            store.save(session)

            return f"{session.id} terminated"

        elif action == "send_message":
            if not message:
                return format_tool_error("params", name="message", detail="required for 'send_message'")

            # Mirror the main agent's semantics: a follow-up can be sent in any
            # status. If the subagent is currently busy (live async_task), the
            # message is queued and drained by the running stream; otherwise it
            # starts immediately.
            if session.async_task and hasattr(session.async_task, "done") and not session.async_task.done():
                if not hasattr(session, "pending_messages"):
                    session.pending_messages = []
                session.pending_messages.append(message)
                return f"queued for {session.id}"

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
                        from core.subagent_stream import configure_subagent_agent

                        configure_subagent_agent(
                            subagent,
                            session.role,
                            app=ctx.app,
                            project_dir=getattr(ctx, "project_dir", None) or session.project_dir,
                        )
                        session.agent = subagent

                # Restore the isolated worktree context for follow-up so the subagent
                # keeps working on its own branch/cwd instead of silently falling back
                # to the parent checkout (worktree is removed on completion).
                if subagent and session.project_dir and session.branch_name:
                    from core.subagent_worktree import SubagentWorktreeManager

                    project_dir = SubagentWorktreeManager.ensure_worktree_available(session, parent_dir=ctx.project_dir)
                    subagent.project_dir = project_dir
                    subagent.cwd = project_dir

                if not subagent:
                    return format_tool_error("context", name=session.id, detail="no active agent")

                session.status = "running"
                if not hasattr(session, "pending_messages"):
                    session.pending_messages = []
                session.pending_messages.append(message)
                session.add_event({"type": "user", "text": message})
                session.add_event({"type": "status_change", "status": "running"})

                from core.subagent_stream import run_subagent_stream_bg
                from core.subagent_worktree import SubagentWorktreeManager
                from tools.base import format_background_notification

                cleanup_fn = SubagentWorktreeManager.make_worktree_cleanup_fn(
                    ctx.project_dir, session.project_dir, session.branch_name, is_followup=True
                )

                notification_hdr = format_background_notification(
                    "Subagent follow-up", session.description, session.id, "{result_text}"
                )

                # The stream drains session.pending_messages inline, so only the
                # first (this) message is passed; queued follow-ups are consumed
                # by the loop until empty, keeping session running.
                bg_task = asyncio.create_task(
                    run_subagent_stream_bg(
                        subagent,
                        session.pending_messages.pop(0),
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

                return f"message sent to {session.id}"
            except Exception as err:
                session.finish(STATUS_ERROR, str(err))
                store.save(session)
                return format_tool_error("subagent_setup", detail=str(err), name=session.id)

        else:
            return format_tool_error("action", detail="valid: list, status, kill, send_message", name=action)
