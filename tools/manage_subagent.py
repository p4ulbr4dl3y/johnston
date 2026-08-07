import asyncio
import os
from typing import Any, Dict

from core.subagent_tracker import SubagentTracker
from tools.base import BaseTool


class ManageSubagentTool(BaseTool):
    name = "manage_subagent"
    description = "Manage active and historical subagents. Actions: list, status, kill, send_message."
    schema = {
        "type": "function",
        "function": {
            "name": "manage_subagent",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "status", "kill", "send_message"],
                        "description": "Action type"
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Target subagent task_id or description"
                    },
                    "message": {
                        "type": "string",
                        "description": "Follow-up message for subagent"
                    },
                    "background": {
                        "type": "boolean",
                        "description": "Run follow-up message asynchronously"
                    }
                },
                "required": ["action"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        ctx = self._ensure_context(app)
        action = (args.get("action") or "").strip().lower()
        task_id = (args.get("task_id") or "").strip()
        message = (args.get("message") or "").strip()

        tracker = SubagentTracker.get_instance()

        curr_session_id = getattr(ctx.app, "current_session_id", None) if ctx.app else None

        if action == "list":
            from core.subagent_registry import SubagentRegistry
            registry = SubagentRegistry.get_instance()
            registry.reload(project_dir=getattr(ctx.app, "project_dir", None))
            defs = registry.list_definitions()

            lines = ["Available Subagent Definitions:"]
            for dname, dval in defs.items():
                lines.append(f"• Type: '{dname}' [{dval.source}] — {dval.description}")

            show_all = bool(args.get("all", False))
            target_sessions = list(tracker.sessions.values()) if show_all else tracker.get_sessions_for_session(curr_session_id)
            if target_sessions:
                lines.append("\nActive/Past Subagent Sessions:")
                for sess in target_sessions:
                    lines.append(
                        f"• ID: {sess.task_id} | Status: {sess.status.upper()} | Type: {sess.subagent_type} | Description: {sess.description}"
                    )
            return "\n".join(lines)

        if not task_id:
            return "ERR: 'task_id' required for '" + action + "'"

        session = tracker.find_session_by_description_or_id(task_id, session_id=curr_session_id)
        if not session:
            return f"ERR: session '{task_id}' not found"

        if action == "status":
            from core.config import SUBAGENT_LOGS_DIR
            log_file = os.path.join(tracker.storage_dir, f"{session.task_id}.json")
            result_log_file = os.path.join(SUBAGENT_LOGS_DIR, f"{session.task_id}.log")

            lines = [
                f"Subagent Status ({session.task_id}):",
                f"• Description: {session.description}",
                f"• Type: {session.subagent_type}",
                f"• Status: {session.status.upper()}",
                f"• Mode: {'Background' if session.background else 'Foreground'}",
                f"• Total Events: {len(session.events)}",
                f"• Full Log File: {log_file}",
                f"• Result Log File: {result_log_file}",
            ]

            if os.path.exists(result_log_file):
                try:
                    with open(result_log_file, "r", encoding="utf-8") as f:
                        log_content = f.read().strip()
                    if log_content:
                        lines.append(f"\nFinal Response Snippet:\n{log_content[:2000]}")
                except Exception:
                    pass

            lines.append("\nRecent Events Log:")

            recent = session.events[-15:]
            for evt in recent:
                etype = evt.get("type")
                if etype == "user":
                    lines.append(f"  [User]: {evt.get('text')}")
                elif etype == "bot_text":
                    lines.append(f"  [Bot]: {evt.get('text')[:150]}...")
                elif etype == "tool":
                    lines.append(f"  [Tool]: {evt.get('tool_type')} ({evt.get('target')})")
                elif etype == "status_change":
                    lines.append(f"  [Status]: {evt.get('status')}")

            if session.status == "running":
                lines.append("\nNote: Subagent is still running. STOP calling manage_subagent(status) in a loop and end your turn now.")
            return "\n".join(lines)

        elif action == "kill":
            if session.status != "running":
                return f"OK: {session.task_id} already in '{session.status}'"

            if session.async_task and not session.async_task.done():
                try:
                    session.async_task.cancel()
                except Exception:
                    pass

            session.finish("cancelled", "Cancelled via manage_subagent tool")

            return f"OK: {session.task_id} terminated"

        elif action == "send_message":
            if not message:
                return "ERR: 'message' required for 'send_message'"

            subagent = session.agent
            if not subagent:
                subagent = ctx.create_agent()
                if subagent:
                    subagent.app = ctx.app
                    subagent.is_subagent = True
                    hist = session.to_dict().get("agent_history", []) if hasattr(session, "to_dict") else []
                    if hist:
                        subagent.history = hist
                    session.agent = subagent

            # Restore the isolated worktree context for follow-up so the subagent
            # keeps working on its own branch/cwd instead of silently falling back
            # to the parent checkout (worktree is removed on completion).
            if subagent and session.project_dir and session.branch_name:
                project_dir = session.project_dir
                branch_name = session.branch_name
                if not os.path.isdir(project_dir):
                    from core.subagent_worktree import SubagentWorktreeManager
                    parent_dir = getattr(ctx.app, "project_dir", None) or os.getcwd()
                    reattached = SubagentWorktreeManager.attach_worktree(parent_dir, session.task_id, branch_name)
                    if reattached:
                        project_dir = reattached
                subagent.project_dir = project_dir
                subagent.cwd = project_dir

            if not subagent:
                return f"ERR: no active agent for {session.task_id}"

            session.add_event({"type": "user", "text": message})

            from core.subagent_tracker import merge_subagent_metrics, record_subagent_step

            def _record_step(step, acc):
                record_subagent_step(step, session, acc)

            def _merge_metrics():
                merge_subagent_metrics(subagent, ctx)
                ctx.refresh_status()

            def _cleanup_followup(acc):
                # Commit any follow-up changes to the subagent's branch and remove
                # the (possibly re-attached) worktree, mirroring invoke_subagent.
                wt_path = session.project_dir
                wt_branch = session.branch_name
                if wt_path and wt_branch and os.path.isdir(wt_path):
                    from core.subagent_worktree import SubagentWorktreeManager
                    parent_dir = getattr(ctx.app, "project_dir", None) or os.getcwd()
                    diff_text, has_changes = SubagentWorktreeManager.get_worktree_diff_summary(
                        parent_dir, wt_path, wt_branch
                    )
                    if has_changes and diff_text:
                        acc[0] = acc[0].rstrip() + (
                            f"\n\n[Worktree Branch '{wt_branch}']\n"
                            f"Changes updated on branch '{wt_branch}'. Run `git merge {wt_branch}` to apply.\n"
                            f"After merging, ask the user via the ask_user tool whether to delete the subagent-created branch '{wt_branch}' before continuing.\n\n"
                            f"{diff_text}"
                        )
                    SubagentWorktreeManager.cleanup_worktree(parent_dir, wt_path, wt_branch, keep_branch=True)

            run_bg = bool(args["background"]) if "background" in args else session.background
            if run_bg:
                async def _run_msg_bg():
                    acc = [""]
                    try:
                        async for step in subagent.stream_steps(message):
                            _record_step(step, acc)
                    except Exception as err:
                        acc[0] = f"[Subagent message error: {err}]"
                    finally:
                        _cleanup_followup(acc)
                        _merge_metrics()
                        msg = (
                            f"[System Notification] Follow-up to background subagent '{session.description}' (ID: {session.task_id}) completed.\n"
                            f"<task_result>\n{acc[0].strip() or 'Completed with no text output.'}\n</task_result>"
                        )
                        ctx.trigger_ai_response(msg)

                bg_task = asyncio.create_task(_run_msg_bg())
                session.async_task = bg_task

                return f"OK: message sent to {session.task_id}"
            else:
                acc = [""]
                try:
                    async for step in subagent.stream_steps(message):
                        _record_step(step, acc)
                except Exception as err:
                    return f"ERR: subagent message: {err}"
                finally:
                    _cleanup_followup(acc)
                    _merge_metrics()

                return f"<task_result>\n{acc[0].strip() or 'Subagent replied with no text output.'}\n</task_result>"

        else:
            return f"ERR: unknown action '{action}'. Valid actions are: list, status, kill, send_message."
