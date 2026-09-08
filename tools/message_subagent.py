from typing import Any, Dict

from core.domain.defaults.errors import ToolResult
from tools.base import BaseTool


class MessageSubagentTool(BaseTool):
    name = "message_subagent"
    interactive_only = True
    subagent_restriction_detail = "subagents cannot message other subagents"
    description = (
        "Send follow-up instructions to an existing subagent session (resumes subagent with its worktree branch and history). "
        "Use when: previous task needs refinement, fixes on partial/failed output, or next steps in the same scope. "
        "Do NOT use for new independent tasks (call invoke_subagent instead)."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "message_subagent",
            "description": (
                "Send follow-up instructions to an existing subagent session (resumes subagent with its worktree branch and history). "
                "Use when: previous task needs refinement, fixes on partial/failed output, or next steps in the same scope. "
                "Do NOT use for new independent tasks (call invoke_subagent instead)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": "Target subagent session ID or title (matches 'id' in <notification>).",
                    },
                    "message": {
                        "type": "string",
                        "description": "Follow-up instruction, clarification, or feedback for the subagent.",
                    },
                },
                "required": ["id", "message"],
            },
        },
    }

    def is_concurrency_safe(self, args: Dict[str, Any] | None = None) -> bool:
        return False

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        ctx = self._ensure_context(ctx)
        err = self.check_context_permissions(ctx)
        if err:
            return err

        args = args or {}
        raw_id = args.get("id")
        session_id = str(raw_id).strip() if raw_id is not None else ""

        raw_message = args.get("message")
        message = str(raw_message).strip() if raw_message is not None else ""

        from core.infrastructure.storage.session_store import get_session_store

        store = get_session_store(ctx.host)
        curr_session_id = ctx.session_id or ""

        if not session_id:
            return ToolResult.error("params", name="id", detail="required")

        if not message:
            return ToolResult.error("params", name="message", detail="required")

        from core.application.session.subagent_service import SubagentService

        session = store.find_session_by_title_or_id(session_id, parent_id=curr_session_id) if store else None
        if not session:
            return ToolResult.error("notfound", name=session_id)

        return await SubagentService.send_message(session, message, ctx, store)
