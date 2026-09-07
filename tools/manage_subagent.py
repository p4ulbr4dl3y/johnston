from typing import Any, Dict

from core.domain.defaults.errors import ToolResult
from tools.base import BaseTool


class ManageSubagentTool(BaseTool):
    name = "manage_subagent"
    description = "Manage subagent sessions: terminate or send follow-up instructions."
    schema = {
        "type": "function",
        "function": {
            "name": "manage_subagent",
            "description": "Manage subagent sessions: terminate or send follow-up instructions.",
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["send_message", "kill"],
                        "description": (
                            "Operation: 'send_message' (resume subagent with new input), 'kill' (terminate session)."
                        ),
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Target subagent session ID (required).",
                    },
                    "message": {
                        "type": "string",
                        "description": "Follow-up text message when action is 'send_message'.",
                    },
                },
                "required": ["action", "session_id"],
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
        curr_session_id = ctx.session_id or ""

        if not action:
            return ToolResult.error("params", name="action", detail="required ('send_message' or 'kill')")

        if action not in ("send_message", "kill"):
            return ToolResult.error("action", detail="valid: send_message, kill", name=action)

        if not session_id:
            return ToolResult.error(
                "params",
                name="session_id",
                detail=f"required for '{action}'.",
            )

        from core.application.session.subagent_service import SubagentService

        session = store.find_session_by_title_or_id(session_id, parent_id=curr_session_id)
        if not session:
            return ToolResult.error("notfound", name=session_id)

        if action == "kill":
            return SubagentService.kill_subagent(session, store)

        elif action == "send_message":
            return await SubagentService.send_message(session, message, ctx, store)

        return ToolResult.error("action", detail="valid: send_message, kill", name=action)

