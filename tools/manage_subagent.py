from typing import Any, Dict

from core.domain.defaults.errors import ToolResult
from tools.base import BaseTool


class ManageSubagentTool(BaseTool):
    name = "manage_subagent"
    description = "Manage subagent sessions: inspect active tasks, terminate, or send follow-up instructions."
    schema = {
        "type": "function",
        "function": {
            "name": "manage_subagent",
            "description": "Manage subagent sessions: inspect active tasks, terminate, or send follow-up instructions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["list", "kill", "send_message"],
                        "description": (
                            "Operation: 'list' (active sessions), 'send_message' (resume subagent with new input), 'kill' (terminate session)."
                        ),
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Target subagent session ID.",
                    },
                    "message": {
                        "type": "string",
                        "description": "Follow-up text message when action is 'send_message'.",
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

        from core.infrastructure.storage.session_store import get_session_store

        store = get_session_store(ctx.host)
        curr_session_id = ctx.session_id

        from core.application.session.subagent_service import SubagentService

        if action == "list":
            target_sessions = SubagentService.list_subagents(store, curr_session_id)
            fp = [(str(getattr(s, "id", "")), str(getattr(s, "status", ""))) for s in (target_sessions or [])]
            last_fp = getattr(self, "_last_list_fp", None)
            count = getattr(self, "_consecutive_list_count", 0)
            if last_fp == fp and count >= 1:
                return ToolResult.error(
                    "execute",
                    detail=(
                        "Consecutive polling of 'list' is blocked. Subagent status has not changed. "
                        "The system automatically wakes you with <notification type='subagent'> on finish. "
                        "Stop calling tools to wait."
                    ),
                    name="manage_subagent",
                )
            self._last_list_fp = fp
            self._consecutive_list_count = count + 1 if last_fp == fp else 1

            content_txt = SubagentService.format_subagents_list(target_sessions)
            return ToolResult.done(content=content_txt, display="")

        self._consecutive_list_count = 0

        if not session_id:
            return ToolResult.error(
                "params",
                name="session_id",
                detail=f"required for '{action}'. Run manage_subagent(action='list') to inspect active session IDs.",
            )

        session = store.find_session_by_title_or_id(session_id, parent_id=curr_session_id)
        if not session:
            return ToolResult.error("notfound", name=session_id)

        if action == "kill":
            return SubagentService.kill_subagent(session, store)

        elif action == "send_message":
            return await SubagentService.send_message(session, message, ctx, store)

        return ToolResult.error("action", detail="valid: list, kill, send_message", name=action)
