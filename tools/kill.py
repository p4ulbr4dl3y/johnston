from typing import Any, Dict

from core.domain.defaults.errors import ToolResult
from tools.base import BaseTool


class KillTool(BaseTool):
    name = "kill"
    interactive_only = True
    subagent_restriction_detail = "subagents cannot terminate tasks or subagents"
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

    def is_concurrency_safe(self, args: Dict[str, Any] | None = None) -> bool:
        return False

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        ctx = self._ensure_context(ctx)
        err = self.check_context_permissions(ctx)
        if err:
            return err

        args = args or {}
        raw_id = (
            args.get("id")
            if "id" in args
            else (args.get("task_id") if "task_id" in args else args.get("session_id"))
        )
        target_id = str(raw_id).strip() if raw_id is not None else ""

        if not target_id:
            return ToolResult.error("params", name="id", detail="required")

        # 1. Check tasks (background and foreground)
        t = ctx.find_task(target_id)
        if t is not None:
            if getattr(t, "is_active", getattr(t, "is_running", False)):
                try:
                    setattr(t, "suppress_notification", True)
                    if hasattr(t, "kill"):
                        await t.kill()
                    elif getattr(t, "process", None) and t.process.returncode is None:
                        from core.infrastructure.platform.process import terminate_process_tree

                        await terminate_process_tree(t.process)
                    ctx.refresh_status()
                    return ToolResult.done(content=f"[killed {target_id}]", display="")
                except Exception as e:
                    return ToolResult.error("kill", detail=str(e), name=target_id)
                finally:
                    output = t.get_formatted_output() if hasattr(t, "get_formatted_output") else "[killed]"
                    ctx.terminate_task_widget(target_id, output=output, status="done")
            else:
                ctx.terminate_task_widget(target_id, output="[killed]", status="done")
                return ToolResult.error("notrunning", name=target_id)

        # 2. Check subagent sessions
        from core.application.session.subagent_service import SubagentService
        from core.infrastructure.storage.session_store import get_session_store

        curr_sid = ctx.session_id or ""
        store = get_session_store(ctx.host)
        session = store.find_session_by_title_or_id(target_id, parent_id=curr_sid) if store else None
        if session is not None:
            return SubagentService.kill_subagent(session, store)

        ctx.detach_shell_widget(target_id)
        return ToolResult.error("notfound", name=target_id)

