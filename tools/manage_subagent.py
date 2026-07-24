import asyncio
from typing import Any, Dict

from core.subagent_tracker import SubagentTracker
from tools.base import BaseTool


class ManageSubagentTool(BaseTool):
    name = "manage_subagent"
    description = (
        "Manage active and historical subagents for current session. "
        "Actions: 'list' (view subagents), 'status' (inspect subagent logs/status), "
        "'kill' (terminate a running subagent), or 'send_message' (send a follow-up prompt to ANY subagent, "
        "including COMPLETED ones. Completed subagents WILL resume, process the message, and respond)."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "manage_subagent",
            "description": "Manage subagents: list subagents, inspect status/logs, terminate subagents, or send follow-up messages to ANY subagent (including COMPLETED ones, which WILL resume and answer).",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "status", "kill", "send_message"],
                        "description": "Action: 'list', 'status', 'kill', or 'send_message' (resumes ANY subagent, completed or running)"
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Subagent task_id or description (required for status, kill, send_message)"
                    },
                    "message": {
                        "type": "string",
                        "description": "Follow-up message to send to the subagent (works on COMPLETED subagents too, resuming them)"
                    },
                    "background": {
                        "type": "boolean",
                        "description": "If true, run follow-up message in background without blocking chat UI"
                    }
                },
                "required": ["action"]
            }
        }
    }

    async def execute(self, args: Dict[str, Any], app: Any = None) -> str:
        ctx = self._ensure_context(app)
        action = args.get("action", "").strip().lower()
        task_id = args.get("task_id", "").strip()
        message = args.get("message", "").strip()

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
            return "Error: 'task_id' parameter is required for action '" + action + "'."

        session = tracker.find_session_by_description_or_id(task_id, session_id=curr_session_id)
        if not session:
            return f"Error: Subagent session '{task_id}' not found."

        if action == "status":
            import os
            log_file = os.path.join(tracker.storage_dir, f"{session.task_id}.json")

            lines = [
                f"Subagent Status ({session.task_id}):",
                f"• Description: {session.description}",
                f"• Type: {session.subagent_type}",
                f"• Status: {session.status.upper()}",
                f"• Mode: {'Background' if session.background else 'Foreground'}",
                f"• Total Events: {len(session.events)}",
                f"• Full Log File: {log_file}",
                "\nRecent Events Log:"
            ]

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

            return "\n".join(lines)

        elif action == "kill":
            if session.status != "running":
                return f"Subagent {session.task_id} is already in state '{session.status}'."

            if session.async_task and not session.async_task.done():
                try:
                    session.async_task.cancel()
                except Exception:
                    pass

            session.finish("cancelled", "Cancelled via manage_subagent tool")
            ctx.notify(f"Subagent {session.task_id} terminated.")
            return f"Subagent {session.task_id} has been terminated."

        elif action == "send_message":
            if not message:
                return "Error: 'message' parameter is required for action 'send_message'."

            subagent = session.agent
            if not subagent:
                subagent = ctx.create_agent()
                if subagent:
                    subagent.app = ctx.app
                    hist = session.to_dict().get("agent_history", []) if hasattr(session, "to_dict") else []
                    if hist:
                        subagent.history = hist
                    session.agent = subagent

            if not subagent:
                return f"Error: No active agent instance available for subagent {session.task_id}."

            session.add_event({"type": "user", "text": message})

            def _record_step(step, acc):
                etype = step[0]
                val1 = step[1] if len(step) > 1 else ""
                val2 = step[2] if len(step) > 2 else ""
                val3 = step[3] if len(step) > 3 else None

                if etype == "thinking_start":
                    session.add_event({"type": "thinking_start", "val1": val1})
                elif etype == "thinking_delta":
                    session.add_event({"type": "thinking_delta", "val1": val1})
                elif etype == "thinking_end":
                    try:
                        dur = float(val1)
                    except Exception:
                        dur = 0.0
                    session.add_event({"type": "thinking_end", "duration": dur, "content": val2})
                elif etype == "tool":
                    targs = val3 if isinstance(val3, dict) else {}
                    session.add_event({"type": "tool", "tool_type": val1, "target": val2, "args": targs})
                elif etype == "tool_result":
                    session.add_event({"type": "tool_result", "result_text": val1})
                elif etype == "bot_chunk":
                    session.add_event({"type": "bot_chunk", "text": val1})
                    acc[0] += val1
                elif etype == "bot_delta":
                    session.add_event({"type": "bot_delta", "text": val1})
                    acc[0] = val1
                elif etype in ("bot_text", "outro"):
                    session.add_event({"type": "bot_text", "text": val1})
                    acc[0] = val1

            def _merge_metrics():
                if ctx.app and hasattr(ctx.app, "agent") and ctx.app.agent:
                    main_agent = ctx.app.agent
                    main_agent.tokens_input += getattr(subagent, "tokens_input", 0)
                    main_agent.tokens_output += getattr(subagent, "tokens_output", 0)
                    main_agent.total_tokens += getattr(subagent, "total_tokens", 0)
                    main_agent.cost_usd += getattr(subagent, "cost_usd", 0.0)
                    ctx.refresh_status()

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
                        _merge_metrics()
                        msg = (
                            f"[System Notification] Follow-up to background subagent '{session.description}' (ID: {session.task_id}) completed.\n"
                            f"<task_result>\n{acc[0].strip() or 'Completed with no text output.'}\n</task_result>"
                        )
                        ctx.trigger_ai_response(msg)

                bg_task = asyncio.create_task(_run_msg_bg())
                session.async_task = bg_task
                ctx.notify(f"Message sent to background subagent {session.task_id}")
                return f"Message sent to background subagent {session.task_id}. You will be notified on completion."
            else:
                acc = [""]
                try:
                    async for step in subagent.stream_steps(message):
                        _record_step(step, acc)
                except Exception as err:
                    return f"Error executing subagent message: {err}"
                finally:
                    _merge_metrics()

                return f"<task_result>\n{acc[0].strip() or 'Subagent replied with no text output.'}\n</task_result>"

        else:
            return f"Error: Unknown action '{action}'. Valid actions are: list, status, kill, send_message."
