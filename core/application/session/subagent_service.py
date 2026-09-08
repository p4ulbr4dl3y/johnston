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
    if isinstance(raw_st, SessionStatus):
        return raw_st in (SessionStatus.ACTIVE, SessionStatus.RUNNING)
    st = str(raw_st or "").lower()
    return st in (SessionStatus.ACTIVE.value, SessionStatus.RUNNING.value)


def resolve_subagent_display_status(session: Any) -> str:
    """Map internal session state to canonical subagent status string."""
    raw_st = getattr(session, "status", None)
    if isinstance(raw_st, SessionStatus):
        st = raw_st.value
    else:
        st = str(raw_st or "").lower()

    if st == SessionStatus.CANCELLED.value:
        return SessionStatus.CANCELLED.value
    if st == SessionStatus.ERROR.value:
        return SessionStatus.ERROR.value
    if st == SessionStatus.COMPLETED.value:
        return SessionStatus.COMPLETED.value
    if getattr(session, "async_task", None) and not session.async_task.done():
        return SessionStatus.RUNNING.value
    if st in (SessionStatus.ACTIVE.value, SessionStatus.RUNNING.value):
        return SessionStatus.RUNNING.value
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
        session_id = gen_sub_id() if callable(gen_sub_id) else f"subagent-{uuid.uuid4().hex[:8]}"

        parent_session_id = ctx.session_id
        if not isinstance(parent_session_id, str) or not parent_session_id:
            parent_session_id = getattr(getattr(ctx, "host", None), "current_session_id", None)
        store.list(kind="subagent")  # ensure subagent sessions for project are loaded

        running_subagents = cls.get_running_subagents(store, parent_session_id)
        settings = settings_provider() if callable(settings_provider) else settings_provider
        max_subagents = settings.subagents.max_concurrent
        if len(running_subagents) >= max_subagents:
            return ToolResult.error(
                "limit", detail=f"{max_subagents} concurrent max; wait or kill(id='...')"
            )

        subagent = ctx.create_agent()
        if not subagent:
            return ToolResult.error("context", name="app", detail="unavailable")

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
                id_tail = session_id.split("-")[-1] if "-" in session_id else session_id[:8]
                if len(slug) >= 3:
                    branch_name = f"subagent/{slug}-{id_tail}"
                else:
                    branch_name = f"subagent/{role_key}-{id_tail}"

            if branch_name != current_branch:
                try:
                    wt_path, wt_branch = await worktree_manager_cls.create_worktree_async(
                        project_dir, session_id, branch_name
                    )
                except Exception as exc:
                    return ToolResult.error("worktree", detail=f"Failed to create git worktree: {exc}")
                if not wt_path:
                    return ToolResult.error("worktree", detail=f"Failed to create git worktree for branch '{branch_name}'")
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
            status=SessionStatus.RUNNING,
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

        task_manager = getattr(ctx, "task_manager", None)
        if task_manager is None and getattr(ctx, "host", None):
            task_manager = getattr(ctx.host, "task_manager", None)
        if task_manager is not None:
            from core.infrastructure.tasks.subagent_task import SubagentTask

            task = SubagentTask(session, store, bg_task)
            task_manager.register(task)

        record_subagent_session(ctx.host, session_id)
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
        """Cancels running subagent asyncio tasks and marks their sessions cancelled.

        Single-writer principle (audit M6): the cancelled task's own teardown
        (``execute_session_turn``'s CancelledError handler inside
        ``run_subagent_stream_bg``) owns the terminal ``finish(CANCELLED)`` +
        save. The sync writer here only takes over when no task teardown will
        run (async_task missing or already done) so finished-but-stale
        sessions are still finalized (audit A6) and cancellation can never
        leave a session unpersisted.
        """
        if not store:
            return 0
        if parent_id:
            sessions = store.children(parent_id)
        else:
            sessions = store.list(kind="subagent")

        cancelled = 0
        for sess in sessions:
            # Finalize finished-but-stale sessions too (A6): a session whose
            # async_task already finished (crashed/completed without follow-up)
            # but whose status is still "running" still gets finalized here.
            if not is_active_subagent(sess):
                continue
            cancelled += 1
            setattr(sess, "suppress_notification", True)
            async_task = getattr(sess, "async_task", None)
            if async_task and not async_task.done():
                try:
                    async_task.cancel()
                except Exception:
                    pass
                # The cancelled task's handler owns the terminal finish+save
                # (it also sees suppress_notification and skips notification).
                continue
            # Fallback (no live task teardown): sync finish + save.
            sess.finish(SessionStatus.CANCELLED, "Cancelled")
            if store:
                store.save(sess)
        return cancelled

    @classmethod
    def kill_subagent(cls, session: AgentSession, store: Any) -> ToolResult:
        """Terminate a running subagent session and cancel its background task.

        Single-writer principle (audit M6): for a live async_task the sync
        path only cancels + sets ``suppress_notification`` — the cancelled
        task's own teardown (``run_subagent_stream_bg`` /
        ``execute_session_turn`` CancelledError handler) owns the terminal
        ``finish(CANCELLED)`` + save, so exactly one status_change and one
        divider land in the persisted file. When no task teardown can run
        (async_task missing or already done — the finished-but-stale case,
        audit A6) the sync finish+save finalizes the session as a fallback.
        """
        if not session:
            return ToolResult.error("session", detail="Session not found")
        setattr(session, "suppress_notification", True)
        if hasattr(session, "pending_messages") and session.pending_messages:
            session.pending_messages.clear()

        async_task = getattr(session, "async_task", None)
        if async_task and not async_task.done():
            try:
                async_task.cancel()
            except Exception:
                pass
            # M6: the live task's own teardown
            # (``execute_session_turn``'s CancelledError handler inside
            # ``run_subagent_stream_bg``) owns the terminal finish + save.
        else:
            # A6: no live task teardown will run. Finalize finished-but-stale
            # sessions (async_task done/missing while status is still
            # active/"running") here; already-terminal sessions (completed /
            # error / cancelled) keep their status — a kill is a no-op there.
            if is_active_subagent(session):
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
