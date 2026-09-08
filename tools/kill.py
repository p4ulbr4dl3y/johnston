from typing import Any, Dict

from core.domain.defaults.errors import ToolResult
from tools.base import BaseTool


class KillTool(BaseTool):
    name = "kill"
    description = "Terminate a running background shell task or subagent session by ID."
    schema = {
        "type": "function",
        "function": {
            "name": "kill",
            "description": "Terminate a running background shell task or subagent session by ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id": {
                        "type": "string",
                        "description": (
                            "ID of the background shell task or subagent session to terminate "
                            "(matches the 'id' attribute from <notification>)."
                        ),
                    },
                },
                "required": ["id"],
            },
        },
    }

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        args = args or {}
        ctx = self._ensure_context(ctx)
        target_id = (args.get("id") or args.get("task_id") or args.get("session_id") or "").strip()

        if not target_id:
            return ToolResult.error("params", name="id", detail="required")

        curr_sid = ctx.session_id or ""

        # 1. Check background tasks
        from core.infrastructure.tasks.manage import filter_to_session

        tasks = filter_to_session(ctx.background_tasks or [], curr_sid)
        t = next(
            (
                task
                for task in tasks
                if getattr(task, "task_id", None) == target_id or getattr(task, "id", None) == target_id
            ),
            None,
        )
        if t is not None:
            if getattr(t, "is_active", getattr(t, "is_running", False)):
                try:
                    setattr(t, "suppress_notification", True)
                    if hasattr(t, "kill"):
                        await t.kill()
                    elif getattr(t, "process", None) and t.process.returncode is None:
                        t.process.kill()
                    ctx.refresh_status()
                    return ToolResult.done(content=f"[killed {target_id}]", display="")
                except Exception as e:
                    return ToolResult.error("kill", detail=str(e), name=target_id)
                finally:
                    if ctx.host and hasattr(ctx.host, "_background_shell_widgets") and isinstance(
                        ctx.host._background_shell_widgets, dict
                    ):
                        widget = ctx.host._background_shell_widgets.pop(target_id, None)
                        if widget is not None and hasattr(widget, "set_result"):
                            try:
                                widget.set_result(
                                    t.get_formatted_output() if hasattr(t, "get_formatted_output") else "[killed]",
                                    status="done",
                                )
                            except Exception:
                                pass
            else:
                if ctx.host and hasattr(ctx.host, "_background_shell_widgets") and isinstance(
                    ctx.host._background_shell_widgets, dict
                ):
                    ctx.host._background_shell_widgets.pop(target_id, None)
                return ToolResult.error("notrunning", name=target_id)

        # 2. Check subagent sessions
        from core.application.session.subagent_service import SubagentService
        from core.infrastructure.storage.session_store import get_session_store

        store = get_session_store(ctx.host)
        session = store.find_session_by_title_or_id(target_id, parent_id=curr_sid) if store else None
        if session is not None:
            return SubagentService.kill_subagent(session, store)

        if ctx.host and hasattr(ctx.host, "_background_shell_widgets") and isinstance(
            ctx.host._background_shell_widgets, dict
        ):
            ctx.host._background_shell_widgets.pop(target_id, None)

        return ToolResult.error("notfound", name=target_id)
