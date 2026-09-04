"""Application service managing the lifecycle of subagents (spawn, inspect, signal, cancel)."""

import asyncio
import logging
import re
import uuid
from typing import Any, List, Optional

from core.domain.defaults.errors import ToolResult, ToolResultStatus
from core.domain.entities.session import AgentSession, SessionStatus
from core.infrastructure.config.settings import get_settings
from core.infrastructure.runtime.git_utils import run_git_async
from core.infrastructure.runtime.subagent_tracker import record_subagent_session
from core.infrastructure.runtime.subagent_worktree import SubagentWorktreeManager
from core.infrastructure.runtime.xml_utils import escape_xml_attr
from core.infrastructure.storage.session_store import get_session_store

logger = logging.getLogger(__name__)


def is_active_subagent(session: Any) -> bool:
    """True if subagent has an active async task or running status."""
    if getattr(session, "async_task", None) and not session.async_task.done():
        return True
    raw_st = getattr(session, "status", None)
    st = raw_st.value.lower() if hasattr(raw_st, "value") else str(raw_st or "").lower()
    return st in ("active", "running")


def resolve_subagent_display_status(session: Any) -> str:
    """Map internal session state to canonical subagent status string."""
    raw_st = getattr(session, "status", None)
    if isinstance(raw_st, SessionStatus):
        st = raw_st.value.lower()
    else:
        st = str(raw_st or "").lower()

    if st in ("cancelled", "canceled", "killed"):
        return "cancelled"
    if st in ("error", "failed"):
        return "error"
    if st in ("completed", "done", "finished"):
        return "completed"
    if getattr(session, "async_task", None) and not session.async_task.done():
        return "running"
    if st in ("active", "running"):
        return "running"
    return st or "unknown"


class SubagentService:
    """Coordinates subagent creation, worktrees, sessions, and execution."""

    @staticmethod
    def list_subagents(store: Any, parent_id: Optional[str] = None) -> List[AgentSession]:
        """List subagents belonging to parent or project."""
        if parent_id:
            return store.children(parent_id)
        return store.list(kind="subagent")

    @classmethod
    def get_running_subagents(cls, store: Any, parent_id: Optional[str] = None) -> List[AgentSession]:
        """Return active running subagents."""
        sessions = cls.list_subagents(store, parent_id)
        return [s for s in sessions if is_active_subagent(s)]

    @classmethod
    async def spawn_subagent(
        cls,
        *,
        prompt: str,
        title: str,
        subagent_type: str = "worker",
        branch_override: str = "",
        ctx: Any,
        worktree_manager_cls: Any = SubagentWorktreeManager,
        settings_provider: Any = get_settings,
    ) -> ToolResult:
        """Spawn an autonomous background subagent with isolated git worktree and session."""
        prompt = (prompt or "").strip()
        title = (title or prompt[:30] or "subagent task").strip()
        subagent_type = (subagent_type or "worker").strip().lower()
        branch_override = (branch_override or "").strip()

        if not prompt:
            return ToolResult.error("params", name="prompt", detail="required")

        store = get_session_store(ctx.host)
        gen_sub_id = getattr(store, "generate_subagent_id", None)
        session_id = gen_sub_id() if callable(gen_sub_id) else uuid.uuid4().hex[:8]

        parent_session_id = ctx.session_id
        if not isinstance(parent_session_id, str) or not parent_session_id:
            parent_session_id = getattr(getattr(ctx, "host", None), "current_session_id", None)
        store.list(kind="subagent")  # ensure subagent sessions for project are loaded

        running_subagents = cls.get_running_subagents(store, parent_session_id)
        settings = settings_provider() if callable(settings_provider) else settings_provider
        max_subagents = settings.subagents.max_concurrent
        if len(running_subagents) >= max_subagents:
            return ToolResult.error(
                "limit", detail=f"{max_subagents} concurrent max; wait or manage_subagent(action='kill')"
            )

        subagent = ctx.create_agent()
        if not subagent:
            return ToolResult.error("context", name="app", detail="unavailable")

        record_subagent_session(ctx.host, session_id)

        wt_path = None
        wt_branch = None
        project_dir = ctx.project_dir

        is_git = worktree_manager_cls.is_git_repo(project_dir)
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
                wt_path, wt_branch = await worktree_manager_cls.create_worktree_async(
                    project_dir, session_id, branch_name
                )
                if wt_path:
                    subagent.project_dir = wt_path
                    subagent.cwd = wt_path
                    subagent.worktree_branch = wt_branch

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

        cleanup_fn = worktree_manager_cls.make_worktree_cleanup_fn(
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

    @classmethod
    def cancel_running_subagents(cls, store: Any, parent_id: Optional[str] = None) -> int:
        """Cancels running subagent asyncio tasks and marks their sessions cancelled."""
        if not store:
            return 0
        if parent_id:
            sessions = store.children(parent_id)
        else:
            sessions = store.list(kind="subagent")

        cancelled = 0
        for sess in sessions:
            if not is_active_subagent(sess):
                continue
            async_task = getattr(sess, "async_task", None)
            if async_task and not async_task.done():
                try:
                    async_task.cancel()
                except Exception:
                    pass
            sess.finish(SessionStatus.CANCELLED, "Cancelled")
            store.save(sess)
            cancelled += 1
        return cancelled

    @classmethod
    def kill_subagent(cls, session: AgentSession, store: Any) -> ToolResult:
        """Terminate a running subagent session and cancel its background task."""
        setattr(session, "suppress_notification", True)
        if hasattr(session, "pending_messages") and session.pending_messages:
            session.pending_messages.clear()

        if not is_active_subagent(session):
            return ToolResult.done(content=f"[killed {session.id}]", display="")

        async_task = getattr(session, "async_task", None)
        if async_task and not async_task.done():
            try:
                async_task.cancel()
            except Exception:
                pass

        session.finish(SessionStatus.CANCELLED, "Cancelled via subagent tool")
        if store:
            store.save(session)
        return ToolResult.done(content=f"[killed {session.id}]", display="")

    @classmethod
    async def send_message(
        cls,
        session: AgentSession,
        message: str,
        ctx: Any,
        store: Any,
    ) -> ToolResult:
        """Send follow-up instructions to a subagent."""
        if not message:
            return ToolResult.error(
                "params",
                name="message",
                detail="required for 'send_message'. Provide the text instructions to send.",
            )
        from core.application.session.stream import send_subagent_followup

        return await send_subagent_followup(session, message, ctx, store)

    @classmethod
    def format_subagents_list(cls, target_sessions: List[AgentSession]) -> str:
        """Format subagent sessions list for tool output."""
        if not target_sessions:
            return "[subagents 0]"

        items = []
        for sess in target_sessions:
            s_id = str(sess.id)
            s_status = resolve_subagent_display_status(sess)
            s_role = str(getattr(sess, "role", "worker") or "worker")
            raw_title = getattr(sess, "title", "") or ""
            if (not raw_title or raw_title.lower() == "untitled") and getattr(sess, "prompt", ""):
                raw_title = getattr(sess, "prompt", "")
            raw_title = raw_title or "(subagent task)"
            s_title = " ".join(str(raw_title).split())
            items.append(f"{s_id}|{s_status}|{s_role}|{s_title}")

        return f"[subagents {len(target_sessions)} | id|status|role|title]\n" + "\n".join(items)
