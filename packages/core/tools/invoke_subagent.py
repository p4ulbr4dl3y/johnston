import copy
from typing import Any, Dict

from core.domain.defaults.errors import ToolResult
from core.infrastructure.config.settings import get_settings
from core.infrastructure.runtime.subagent_worktree import SubagentWorktreeManager
from tools.base import BaseTool


class InvokeSubagentTool(BaseTool):
    name = "invoke_subagent"
    interactive_only = True
    subagent_restriction_detail = "subagents cannot spawn nested subagents"
    description = (
        "Launch an autonomous subagent in the background to execute an isolated task. Yield turn immediately after launch."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "invoke_subagent",
            "description": (
                "Launch an autonomous subagent in the background to execute an isolated task. Yield turn immediately after launch."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "role": {
                        "type": "string",
                        "enum": ["worker", "explorer", "reviewer"],
                        "description": "Subagent role name from available roles (default: 'worker')",
                    },
                    "title": {
                        "type": "string",
                        "description": (
                            "Short task title in English as a noun phrase (3-5 words, e.g. 'Auth token refactor')."
                        ),
                    },
                    "task": {
                        "type": "string",
                        "description": (
                            "Actionable task instructions, context, acceptance criteria, and expected verification."
                        ),
                    },
                },
                "required": ["title", "task"],
            },
        },
    }

    def is_concurrency_safe(self, args: Dict[str, Any] | None = None) -> bool:
        return False

    def get_schema(self, is_subagent: bool = False) -> Dict[str, Any]:
        from core.role_registry import RoleRegistry

        schema = copy.deepcopy(self.schema)
        try:
            roles = sorted(RoleRegistry.get_instance().list_subagent_roles().keys())
            if roles and "role" in schema.get("function", {}).get("parameters", {}).get("properties", {}):
                schema["function"]["parameters"]["properties"]["role"]["enum"] = roles
        except Exception:
            pass
        return schema

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        ctx = self._ensure_context(ctx)
        err = self.check_context_permissions(ctx)
        if err:
            return err

        args = args or {}
        from core.application.session.subagent_service import SubagentService

        raw_task = args.get("task")
        task_str = str(raw_task) if raw_task is not None else ""

        raw_title = args.get("title")
        title_str = str(raw_title) if raw_title is not None else ""

        raw_role = args.get("role") or "worker"
        role_str = str(raw_role)

        return await SubagentService.spawn_subagent(
            prompt=task_str,
            title=title_str,
            subagent_type=role_str,
            branch_override="",
            ctx=ctx,
            worktree_manager_cls=SubagentWorktreeManager,
            settings_provider=get_settings,
        )
