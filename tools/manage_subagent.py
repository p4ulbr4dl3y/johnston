from typing import Any, Dict

from core.domain.defaults.errors import ToolResult
from core.domain.entities.session import SessionStatus
from tools.base import BaseTool


class ManageSubagentTool(BaseTool):
    name = "manage_subagent"
    description = (
        "Manage subagents: list active sessions, kill running tasks, or send follow-up messages. "
        "Follow-ups resume finished agents or queue if busy."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "manage_subagent",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "kill", "send_message"],
                        "description": "Action to perform",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Subagent session_id (required for 'kill' and 'send_message')",
                    },
                    "message": {
                        "type": "string",
                        "description": (
                            "Follow-up text for 'send_message' (queues if running, resumes if completed)"
                        ),
                    },
                },
                "required": ["action"],
            },
        },
    }

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        args = args or {}
        ctx = self._ensure_context(ctx)
        action = (args.get("action") or "").strip().lower()
        session_id = (args.get("session_id") or "").strip()
        message = (args.get("message") or "").strip()

        from tools.utils import get_session_store

        store = get_session_store(ctx.host)
        curr_session_id = ctx.session_id

        if action == "list":
            target_sessions = store.children(curr_session_id) if curr_session_id else store.list(kind="subagent")
            if not target_sessions:
                return ToolResult.done("No subagent sessions found for current session.")
            lines = ["Active/Past Subagent Sessions:"]
            for sess in target_sessions:
                lines.append(
                    f"• ID: {sess.id} | Status: {sess.status.upper()} | Type: {sess.role} | Title: {sess.description}"
                )
            return ToolResult.done("\n".join(lines))

        if not session_id:
            return ToolResult.error(
                "params",
                name="session_id",
                detail=f"required for '{action}'. Run manage_subagent(action='list') to inspect active session IDs.",
            )

        session = store.find_session_by_description_or_id(session_id, parent_id=curr_session_id)
        if not session:
            return ToolResult.error("notfound", name=session_id)

        if action == "kill":
            if session.status != "running":
                return ToolResult.done(f"{session.id} already in '{session.status}'")

            if session.async_task and not session.async_task.done():
                try:
                    session.async_task.cancel()
                except Exception:
                    pass

            session.finish(SessionStatus.CANCELLED, "Cancelled via subagent tool")
            store.save(session)
            return ToolResult.done(f"{session.id} terminated")

        elif action == "send_message":
            if not message:
                return ToolResult.error(
                    "params",
                    name="message",
                    detail="required for 'send_message'. Provide the text instructions to send.",
                )
            from core.application.session.stream import send_subagent_followup

            return await send_subagent_followup(session, message, ctx, store)

        return ToolResult.error("action", detail="valid: list, kill, send_message", name=action)
