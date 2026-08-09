import asyncio
import os
from typing import Any, Dict

from core.session_manager import (
    STATUS_CANCELLED,
    STATUS_COMPLETED,
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
                    "task_id": {"type": "string", "description": "Target task session_id or description"},
                    "message": {"type": "string", "description": "Follow-up message for subagent"},
                    "background": {"type": "boolean", "description": "Run follow-up message asynchronously"}
                },
                "required": ["action"]
            }
        }
    }

    def _get_store(self, app: Any) -> SessionStore:
        if app and getattr(app, "sm", None):
            return app.sm
        return SessionStore.get_instance()

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        ctx = self._ensure_context(app)
        action = (args.get("action") or "").strip().lower()
        session_id = (args.get("session_id") or "").strip()
        message = (args.get("message") or "").strip()

        store = self._get_store(ctx.app)

        curr_session_id = getattr(ctx.app, "current_session_id", None) if ctx.app else None

        if action == "list":
            from core.role_registry import RoleRegistry
            registry = RoleRegistry.get_instance()
            registry.reload(project_dir=getattr(ctx.app, "project_dir", None))
            defs = registry.list_subagent_roles()

            lines = ["Available Subagent Roles:"]
            for dname, dval in defs.items():
                lines.append(f"• Type: '{dname}' [{dval.source}] — {dval.description}")

            show_all = bool(args.get("all", False))
            if show_all:
                target_sessions = store.list(kind="subagent")
            else:
                target_sessions = store.get_subagents_for_parent(curr_session_id) if curr_session_id else store.list(kind="subagent")
            if target_sessions:
                lines.append("\nActive/Past Subagent Sessions:")
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

                lines.append("\nNote: Subagent is still running. STOP calling manage_subagent(status) in a loop and end your turn now.")
            return "\n".join(lines)

        elif action == "kill":
            if session.status != "running":
                return f"OK: {session.id} already in '{session.status}'"

            if session.async_task and not session.async_task.done():
                try:
                    session.async_task.cancel()
                except Exception:
                    pass

            session.finish(STATUS_CANCELLED, "Cancelled via manage_subagent tool")
            store.save(session)

            return f"OK: {session.id} terminated"

        elif action == "send_message":
            if not message:
                return format_tool_error("params", name="message", detail="required for 'send_message'")

            subagent = session.agent
            if not subagent:
                subagent = ctx.create_agent()
                if subagent:
                    subagent.app = ctx.app
                    subagent.is_subagent = True
                    hist = session.agent_history
                    if hist:
                        subagent.history = hist
                    # Restore role behavior (system prompt, model, tool filtering)
                    # so follow-ups match the original spawn, even after restart.
                    from core.subagent_tracker import apply_subagent_role
                    apply_subagent_role(
                        subagent,
                        session.role,
                        project_dir=getattr(ctx, "project_dir", None) or session.project_dir,
                    )
                    session.agent = subagent

            # Restore the isolated worktree context for follow-up so the subagent
            # keeps working on its own branch/cwd instead of silently falling back
            # to the parent checkout (worktree is removed on completion).
            if subagent and session.project_dir and session.branch_name:
                project_dir = session.project_dir
                branch_name = session.branch_name
                if not os.path.isdir(project_dir):
                    from core.subagent_worktree import SubagentWorktreeManager
                    parent_dir = ctx.project_dir
                    reattached = SubagentWorktreeManager.attach_worktree(parent_dir, session.id, branch_name)
                    if reattached:
                        project_dir = reattached
                subagent.project_dir = project_dir
                subagent.cwd = project_dir

            if not subagent:
                return format_tool_error("context", name=session.id, detail="no active agent")

            session.status = "running"
            session.add_event({"type": "user", "text": message})
            session.add_event({"type": "status_change", "status": "running"})

            from core.subagent_tracker import (
                merge_subagent_metrics,
                record_subagent_step,
                run_subagent_stream_bg,
            )
            from core.subagent_worktree import SubagentWorktreeManager

            def _cleanup_followup(acc):
                wt_path = session.project_dir
                wt_branch = session.branch_name
                SubagentWorktreeManager.append_worktree_diff_to_acc(
                    ctx.project_dir, wt_path, wt_branch, acc, is_followup=True
                )

            run_bg = bool(args["background"]) if "background" in args else session.background if hasattr(session, "background") else True
            if run_bg:
                from tools.base import format_background_notification
                notification_hdr = format_background_notification("Subagent follow-up", session.description, session.id, "{result_text}")
                bg_task = asyncio.create_task(
                    run_subagent_stream_bg(
                        subagent,
                        message,
                        session,
                        ctx,
                        store,
                        cleanup_fn=_cleanup_followup,
                        error_prefix="Subagent message error",
                        notification_template=notification_hdr,
                        session_id=session.id,
                        truncate_result=False,
                    )
                )
                session.async_task = bg_task

                return f"OK: message sent to {session.id}"
            else:
                acc = [""]
                try:
                    async for step in subagent.stream_steps(message):
                        record_subagent_step(step, session, acc)
                    session.finish(STATUS_COMPLETED)
                    store.save(session)
                except asyncio.CancelledError:
                    session.finish(STATUS_CANCELLED, "Cancelled by user")
                    store.save(session)
                    return format_tool_error("cancelled", name=session.id, detail="message cancelled")
                except Exception as err:
                    session.finish(STATUS_ERROR, str(err))
                    store.save(session)
                    return format_tool_error("subagent", detail=str(err), name=session.id)
                finally:
                    _cleanup_followup(acc)
                    merge_subagent_metrics(subagent, ctx)

                return f"<task_result>\n{acc[0].strip() or 'Subagent replied with no text output.'}\n</task_result>"

        else:
            return format_tool_error("action", detail="valid: list, status, kill, send_message", name=action)
