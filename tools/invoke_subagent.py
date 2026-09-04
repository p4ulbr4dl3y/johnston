import asyncio
import copy
import re
import uuid
from typing import Any, Dict

from core.domain.defaults.errors import ToolResult, ToolResultStatus
from core.infrastructure.config.settings import get_settings
from core.infrastructure.runtime.subagent_tracker import (
    _record_subagent_session,
)
from core.infrastructure.runtime.subagent_worktree import SubagentWorktreeManager
from core.infrastructure.runtime.xml_utils import escape_xml_attr
from tools.base import BaseTool


class InvokeSubagentTool(BaseTool):
    name = "invoke_subagent"
    description = (
        "Launch an autonomous subagent in the background for a bounded task (up to concurrent limit). "
        "After launching: STOP calling tools immediately. "
        "Runtime automatically wakes you with <notification type='subagent'> on finish — NEVER poll "
        "manage_subagent(list) to wait. Manage or follow up via 'manage_subagent'."
    )
    schema = {
        "type": "function",
        "function": {
            "name": "invoke_subagent",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": (
                            "Short task title in English as a noun phrase (3-5 words, "
                            "e.g. 'Auth token refactor', 'Query performance audit', not verbs)"
                        ),
                    },
                    "prompt": {
                        "type": "string",
                        "description": (
                            "Task instructions with clear boundaries, relative file paths only "
                            "(do NOT include absolute project paths), and expected output format"
                        ),
                    },
                    "type": {
                        "type": "string",
                        "enum": ["worker", "explorer"],
                        "description": "Subagent role name from available roles (default: 'worker')",
                    },
                },
                "required": ["title", "prompt"],
            },
        },
    }

    def get_schema(self, is_subagent: bool = False) -> Dict[str, Any]:
        from core.role_registry import RoleRegistry

        schema = copy.deepcopy(self.schema)
        try:
            roles = sorted(RoleRegistry.get_instance().list_subagent_roles().keys())
            if roles and "type" in schema.get("function", {}).get("parameters", {}).get("properties", {}):
                schema["function"]["parameters"]["properties"]["type"]["enum"] = roles
        except Exception:
            pass
        return schema

    async def execute(self, args: Dict[str, Any], ctx: Any = None) -> ToolResult:
        ctx = self._ensure_context(ctx)
        args = args or {}
        prompt = (args.get("prompt") or "").strip()
        title = (args.get("title") or prompt[:30] or "subagent task").strip()
        subagent_type = (args.get("type") or "worker").strip().lower()
        branch_override = (args.get("branch") or "").strip()

        if not prompt:
            return ToolResult.error("params", name="prompt", detail="required")

        from core.infrastructure.storage.session_store import get_session_store

        store = get_session_store(ctx.host)
        gen_sub_id = getattr(store, "generate_subagent_id", None)
        session_id = gen_sub_id() if callable(gen_sub_id) else uuid.uuid4().hex[:8]
        args = {**args, "session_id": session_id}

        _record_subagent_session(ctx.host, session_id)

        parent_session_id = ctx.session_id
        if not isinstance(parent_session_id, str) or not parent_session_id:
            parent_session_id = getattr(getattr(ctx, "host", None), "current_session_id", None)
        store.list(kind="subagent")  # ensure subagent sessions for project are loaded

        def _is_active_subagent(s: Any) -> bool:
            if getattr(s, "async_task", None) and not s.async_task.done():
                return True
            raw_st = getattr(s, "status", None)
            st = raw_st.value.lower() if hasattr(raw_st, "value") else str(raw_st or "").lower()
            return st in ("active", "running")

        active_sessions = store.children(parent_session_id) if parent_session_id else store.list(kind="subagent")
        running_subagents = [s for s in active_sessions if _is_active_subagent(s)]
        max_subagents = get_settings().subagents.max_concurrent
        if len(running_subagents) >= max_subagents:
            return ToolResult.error(
                "limit", detail=f"{max_subagents} concurrent max; wait or manage_subagent(action='kill')"
            )

        subagent = ctx.create_agent()
        if not subagent:
            return ToolResult.error("context", name="app", detail="unavailable")

        wt_path = None
        wt_branch = None
        project_dir = ctx.project_dir

        from core.infrastructure.runtime.git_utils import run_git_async

        is_git = SubagentWorktreeManager.is_git_repo(project_dir)
        current_branch = ""
        if is_git:
            res = await run_git_async(["branch", "--show-current"], cwd=project_dir, timeout=5)
            current_branch = res.stdout.strip()

        from core.role_registry import RoleRegistry
        from core.roles.resolve import resolve_role

        registry = RoleRegistry.get_instance()
        role_def = resolve_role(registry, subagent_type, project_dir=project_dir)
        is_read_only = getattr(role_def, "read_only", False)

        branch_name = branch_override
        if is_git and not is_read_only:
            if not branch_name:
                slug = re.sub(r"[^a-zA-Z0-9]+", "-", title).strip("-").lower()[:30]
                role_key = getattr(role_def, "key", "worker") or "worker"
                if len(slug) >= 3:
                    branch_name = f"subagent/{slug}-{session_id[:8]}"
                else:
                    branch_name = f"subagent/{role_key}-{session_id[:8]}"

            if branch_name != current_branch:
                wt_path, wt_branch = await SubagentWorktreeManager.create_worktree_async(
                    project_dir, session_id, branch_name
                )
                if wt_path:
                    subagent.project_dir = wt_path
                    subagent.cwd = wt_path
                    subagent.worktree_branch = wt_branch

        # Apply role definition: system prompt, model, and tool filtering. Do this
        # BEFORE creating the session so session.role captures the canonically
        # applied role (apply_subagent_role falls back to 'worker' for empty,
        # unknown, or main-only roles), not the raw caller-supplied subagent_type.
        from core.application.session.stream import configure_subagent_agent

        applied_role = configure_subagent_agent(
            subagent,
            subagent_type,
            app=ctx.host,
            project_dir=project_dir,
            worktree_branch=wt_branch,
        )
        canonical_role = getattr(subagent, "role", None) or getattr(applied_role, "key", None) or "worker"

        session = store.create_subagent(
            parent_id=parent_session_id or "",
            subagent_id=session_id,
            role=canonical_role,
            title=title,
            prompt=prompt,
            status="running",
            project_dir=wt_path or "",
            branch_name=wt_branch or "",
        )
        session.agent = subagent
        subagent.session = session
        session.add_event({"type": "user", "text": prompt})

        from core.application.session.stream import run_subagent_stream_bg

        cleanup_fn = SubagentWorktreeManager.make_worktree_cleanup_fn(
            project_dir, wt_path, wt_branch, is_followup=False
        )

        bg_task = asyncio.create_task(
            run_subagent_stream_bg(
                subagent,
                prompt,
                session,
                ctx,
                store,
                cleanup_fn=cleanup_fn,
                error_prefix="Subagent error",
                notification_template=True,
                session_id=session_id,
                truncate_result=True,
            )
        )
        session.async_task = bg_task
        ctx.refresh_status()

        branch_info = f" | branch {escape_xml_attr(wt_branch)}" if wt_branch else ""
        content_txt = f"[subagent started | id {session_id} | role {escape_xml_attr(canonical_role)}{branch_info}]"
        return ToolResult(
            status=ToolResultStatus.RUNNING,
            content=content_txt,
            display="",
        )
