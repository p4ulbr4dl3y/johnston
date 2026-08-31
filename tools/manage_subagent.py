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

        from core.infrastructure.storage.session_store import get_session_store

        store = get_session_store(ctx.host)
        curr_session_id = ctx.session_id

        if action == "list":
            target_sessions = store.children(curr_session_id) if curr_session_id else store.list(kind="subagent")
            if not target_sessions:
                return ToolResult.done(
                    content="[subagents 0]",
                    display="No subagent sessions found for current session.",
                )

            items = []
            disp_lines = ["Active/Past Subagent Sessions:"]
            for sess in target_sessions:
                s_id = str(sess.id)
                raw_st = getattr(sess, "status", None)
                if isinstance(raw_st, SessionStatus):
                    st = raw_st.value.lower()
                else:
                    st = str(raw_st or "").lower()

                if getattr(sess, "async_task", None) and not sess.async_task.done():
                    s_status = "running"
                elif st in ("active", "running"):
                    s_status = "running"
                elif st in ("completed", "done", "finished"):
                    s_status = "completed"
                elif st in ("cancelled", "canceled", "killed"):
                    s_status = "cancelled"
                elif st in ("error", "failed"):
                    s_status = "error"
                else:
                    s_status = st or "unknown"

                s_role = str(sess.role or "worker")
                raw_title = getattr(sess, "title", "") or ""
                if (not raw_title or raw_title.lower() == "untitled") and getattr(sess, "prompt", ""):
                    raw_title = getattr(sess, "prompt", "")
                raw_title = raw_title or "(subagent task)"
                s_title = " ".join(str(raw_title).split())
                items.append(f"{s_id}|{s_status}|{s_role}|{s_title}")
                disp_lines.append(
                    f"• ID: {sess.id} | Status: {s_status.upper()} | Type: {s_role.capitalize()} | Title: {s_title}"
                )

            content_txt = f"[subagents {len(target_sessions)} | id|status|role|title]\n" + "\n".join(items)
            display_txt = "\n".join(disp_lines)
            return ToolResult.done(content=content_txt, display=display_txt)

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
            if session.status != "running":
                msg = f"[killed {session.id}]"
                return ToolResult.done(content=msg, display=msg)

            if session.async_task and not session.async_task.done():
                try:
                    session.async_task.cancel()
                except Exception:
                    pass

            session.finish(SessionStatus.CANCELLED, "Cancelled via subagent tool")
            store.save(session)
            msg = f"[killed {session.id}]"
            return ToolResult.done(content=msg, display=msg)

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
