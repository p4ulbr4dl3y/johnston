"""Johnston client facade — in-process API for Johnston core.

Zero imports from textual or johnston.tui.
All methods exchange strongly-typed DTOs defined in johnston.core.dto.
"""
from __future__ import annotations

import logging
import re
import subprocess
import time
from typing import Any, AsyncIterator

from johnston.core.application.provider.provider_manager import ProviderManager
from johnston.core.application.roles.apply import apply_role
from johnston.core.application.rules.rules import RulesManager
from johnston.core.application.session.actions import compact_session, get_rewind_git_stats
from johnston.core.application.skills.manager import get_skill_manager
from johnston.core.domain.policies.role_policy import AgentMode
from johnston.core.dto import (
    CompactionResultDTO,
    ContentDeltaDTO,
    ErrorEventDTO,
    GitStateDTO,
    MessageDTO,
    ModelInfoDTO,
    ProviderDTO,
    RewindPointDTO,
    RuleDTO,
    SessionDTO,
    SessionSummaryDTO,
    SkillDTO,
    StreamEventDTO,
    TaskDTO,
    ToolCallDTO,
    TurnCompletedDTO,
    WorkspaceRootDTO,
    WorktreeDTO,
    parse_event_dto,
)
from johnston.core.infrastructure.platform.git_metrics import get_branch_info, get_diff_metrics, get_diff_stats
from johnston.core.infrastructure.storage.session_store import SessionStore

logger = logging.getLogger(__name__)


def _parse_rewind_stat_numbers(git_stats: str) -> tuple[int, int, bool]:
    """Extract (insertions, deletions, is_available) from git_stats summary."""
    if not git_stats:
        return 0, 0, True
    if git_stats == "diff unavailable":
        return 0, 0, False
    adds = 0
    dels = 0
    m_add = re.search(r"\+(\d+)", git_stats)
    if m_add:
        adds = int(m_add.group(1))
    m_del = re.search(r"-(\d+)", git_stats)
    if m_del:
        dels = int(m_del.group(1))
    return adds, dels, True


class JohnstonClient:
    """Primary in-process facade for programmatic interaction with Johnston core."""

    def __init__(
        self,
        provider: str | None = None,
        model: str | None = None,
        role: str = "worker",
        mode: Any = None,
        effort: str | None = None,
        sandbox: bool | None = None,
        session_id: str | None = None,
        branch: str | None = None,
        pm: Any | None = None,
        store: Any | None = None,
        agent: Any | None = None,
        task_manager: Any | None = None,
        perm_manager: Any | None = None,
    ) -> None:
        self.pm = pm if pm is not None else ProviderManager()
        self.store = store if store is not None else SessionStore.get_instance()
        self.task_manager = task_manager
        self.perm_manager = perm_manager
        self.role = role
        self.mode = mode or AgentMode.HEADLESS
        self.effort = effort
        self.sandbox = sandbox
        self.branch = branch

        # Provider and model resolution
        if provider:
            self.provider = provider
        elif hasattr(self.pm, "get_active_provider_key"):
            self.provider = self.pm.get_active_provider_key() or ""
        else:
            self.provider = ""

        if model:
            self.model = model
        elif self.provider and hasattr(self.pm, "get_provider_model"):
            res = self.pm.get_provider_model(self.provider)
            self.model = res if isinstance(res, str) else ""
        else:
            self.model = ""

        # Agent creation or assignment
        if agent is not None:
            self.agent = agent
        elif self.provider and hasattr(self.pm, "create_agent_for_provider"):
            self.agent = self.pm.create_agent_for_provider(self.provider)
        else:
            self.agent = None

        if self.agent is not None:
            if self.role:
                try:
                    apply_role(self.agent, self.role, mode=self.mode)
                except Exception:
                    logger.debug("Failed to apply role %s to agent", self.role, exc_info=True)
            if self.model:
                setattr(self.agent, "model", self.model)
            if self.effort:
                norm_effort = self.effort.strip().lower()
                setattr(self.agent, "thinking_effort", norm_effort)
                setattr(self.agent, "reasoning_effort", norm_effort)
            if self.sandbox is not None:
                setattr(self.agent, "sandbox_enabled", self.sandbox)
            if self.branch:
                setattr(self.agent, "worktree_branch", self.branch)

        # Session initialization
        self.session: Any = None
        self.session_id: str = session_id or ""
        if self.store is not None:
            is_resumed = False
            if session_id:
                if hasattr(self.store, "get"):
                    self.session = self.store.get(session_id)
                    if self.session is not None:
                        is_resumed = True
                if self.session is None and hasattr(self.store, "create_main"):
                    self.session = self.store.create_main(session_id=session_id, role=self.role)
            else:
                if hasattr(self.store, "generate_session_id") and hasattr(self.store, "create_main"):
                    generated_id = self.store.generate_session_id()
                    self.session = self.store.create_main(session_id=generated_id, role=self.role)
                    self.session_id = generated_id

            if self.session is not None and is_resumed:
                if hasattr(self.session, "agent_history") and self.session.agent_history and self.agent:
                    self.agent.history = list(self.session.agent_history)
                if hasattr(self.agent, "messages"):
                    self.agent.messages = list(getattr(self.session, "messages", []) or getattr(self.session, "agent_history", []))
                for attr in ("tokens_input", "tokens_output", "total_tokens", "cost_usd"):
                    val = getattr(self.session, attr, None)
                    if isinstance(val, (int, float)) and hasattr(self.agent, attr):
                        setattr(self.agent, attr, val)
                if not self.session_id and hasattr(self.session, "id") and self.session.id:
                    self.session_id = str(self.session.id)

    async def stream(
        self,
        prompt: str,
        attachments: list[Any] | None = None,
    ) -> AsyncIterator[StreamEventDTO]:
        """Stream turn steps as typed StreamEventDTO instances."""
        start_time = time.time()
        turn_completed_emitted = False

        if not self.agent:
            yield ErrorEventDTO(message="No active agent available", fatal=True)
            return

        if not hasattr(self.agent, "stream_steps"):
            yield ErrorEventDTO(message="Active agent does not support streaming", fatal=True)
            return

        # Record user prompt in active session if present
        if self.session is not None and hasattr(self.session, "messages"):
            user_msg = {
                "type": "user",
                "role": "user",
                "text": prompt,
                "content": prompt,
                "timestamp": time.time(),
            }
            if attachments:
                user_msg["attachments"] = attachments
            self.session.messages.append(user_msg)

        try:
            if attachments is not None:
                try:
                    step_iter = self.agent.stream_steps(prompt, attachments=attachments)
                except TypeError:
                    step_iter = self.agent.stream_steps(prompt)
            else:
                step_iter = self.agent.stream_steps(prompt)

            async for step in step_iter:
                if isinstance(step, StreamEventDTO):
                    event = step
                else:
                    event = parse_event_dto(step)

                if isinstance(event, TurnCompletedDTO):
                    turn_completed_emitted = True

                yield event

        except Exception as exc:
            logger.debug("Error during client stream: %s", exc, exc_info=True)
            yield ErrorEventDTO(message=str(exc), fatal=False)
            return

        finally:
            if self.session is not None:
                if hasattr(self.agent, "history") and self.agent.history:
                    self.session.agent_history = list(self.agent.history)
                if hasattr(self.agent, "messages") and self.agent.messages:
                    self.session.messages = list(self.agent.messages)
                for attr in ("tokens_input", "tokens_output", "total_tokens", "cost_usd"):
                    if hasattr(self.agent, attr):
                        setattr(self.session, attr, getattr(self.agent, attr))
                if self.store and hasattr(self.store, "save"):
                    try:
                        self.store.save(self.session)
                    except Exception:
                        pass

        if not turn_completed_emitted:
            duration_s = round(time.time() - start_time, 3)
            usage = {
                "tokens_input": getattr(self.agent, "tokens_input", 0),
                "tokens_output": getattr(self.agent, "tokens_output", 0),
                "total_tokens": getattr(self.agent, "total_tokens", 0),
                "cost_usd": getattr(self.agent, "cost_usd", 0.0),
            }
            yield TurnCompletedDTO(duration_s=duration_s, usage=usage)

    async def prompt(
        self,
        prompt: str,
        attachments: list[Any] | None = None,
    ) -> TurnCompletedDTO:
        """Run single non-streaming turn, accumulating text and tool calls."""
        text_parts: list[str] = []
        tool_calls: list[Any] = []
        completed_dto: TurnCompletedDTO | None = None

        async for event in self.stream(prompt, attachments=attachments):
            if isinstance(event, ContentDeltaDTO):
                text_parts.append(event.text)
            elif isinstance(event, ToolCallDTO):
                tool_calls.append(event)
            elif isinstance(event, TurnCompletedDTO):
                completed_dto = event

        full_text = "".join(text_parts)
        duration = completed_dto.duration_s if completed_dto else 0.0
        usage = dict(completed_dto.usage) if completed_dto else {}

        return TurnCompletedDTO(
            duration_s=duration,
            usage=usage,
            text=full_text,
            tool_calls=tool_calls,
        )

    def get_sessions(self) -> list[SessionSummaryDTO]:
        """List all saved sessions from store as SessionSummaryDTO."""
        if not self.store:
            return []

        raw_sessions: list[Any] = []
        if hasattr(self.store, "list_main_sessions"):
            raw_sessions = self.store.list_main_sessions()
        elif hasattr(self.store, "list"):
            raw_sessions = self.store.list(kind="main")

        summaries: list[SessionSummaryDTO] = []
        for s in raw_sessions:
            if isinstance(s, dict):
                sid = str(s.get("id", ""))
                title = str(s.get("title", ""))
                created_at = float(s.get("created_at") or 0.0)
                updated_at = float(s.get("updated_at") or 0.0)
                msg_count = int(s.get("message_count") or s.get("turn_count") or 0)
                tok_count = int(s.get("total_tokens") or s.get("token_count") or 0)
            else:
                sid = str(getattr(s, "id", ""))
                title = str(getattr(s, "title", ""))
                created_at = float(getattr(s, "created_at", 0.0) or 0.0)
                updated_at = float(getattr(s, "updated_at", 0.0) or 0.0)
                msg_count = int(getattr(s, "message_count", 0) or getattr(s, "turn_count", 0) or 0)
                tok_count = int(getattr(s, "total_tokens", 0) or getattr(s, "token_count", 0) or 0)

            summaries.append(
                SessionSummaryDTO(
                    id=sid,
                    title=title,
                    created_at=created_at,
                    updated_at=updated_at,
                    message_count=msg_count,
                    token_count=tok_count,
                )
            )
        return summaries

    def get_session(self, session_id: str | None = None) -> SessionDTO | None:
        """Get session details by ID (or current session) as SessionDTO."""
        target_id = session_id or self.session_id
        if not self.store or not target_id:
            return None

        sess = self.store.get(target_id) if hasattr(self.store, "get") else None
        if sess is None:
            return None

        msg_dtos: list[MessageDTO] = []
        raw_messages = getattr(sess, "messages", []) or []
        for m in raw_messages:
            if isinstance(m, MessageDTO):
                msg_dtos.append(m)
            elif isinstance(m, dict):
                role = str(m.get("role") or m.get("type") or "user")
                content = str(m.get("content") or m.get("text") or m.get("display_text") or "")
                timestamp = float(m.get("timestamp") or m.get("time") or 0.0)
                tool_calls = list(m.get("tool_calls") or [])
                attachments = list(m.get("attachments") or [])
                msg_dtos.append(
                    MessageDTO(
                        role=role,
                        content=content,
                        timestamp=timestamp,
                        tool_calls=tool_calls,
                        attachments=attachments,
                    )
                )

        return SessionDTO(
            id=str(getattr(sess, "id", target_id)),
            title=str(getattr(sess, "title", "")),
            created_at=float(getattr(sess, "created_at", 0.0) or 0.0),
            updated_at=float(getattr(sess, "updated_at", 0.0) or 0.0),
            messages=msg_dtos,
        )

    async def compact(self) -> CompactionResultDTO:
        """Run session compaction for active agent and session."""
        if not self.agent:
            return CompactionResultDTO(
                success=False,
                tokens_before=0,
                tokens_after=0,
                summary="",
                error="No active agent configured",
            )

        def _save():
            if self.store and self.session and hasattr(self.store, "save"):
                try:
                    self.store.save(self.session)
                except Exception:
                    pass

        try:
            outcome = await compact_session(
                self.agent,
                save_session_cb=_save,
                on_begin=lambda: None,
                on_divider_update=lambda _: None,
                refresh_footer_cb=lambda: None,
                session=self.session,
            )
            tokens_before = outcome.tokens.before if outcome.tokens and outcome.tokens.before is not None else 0
            tokens_after = outcome.tokens.after if outcome.tokens and outcome.tokens.after is not None else 0
            err_msg = None if outcome.success else (outcome.message or "Compaction failed")
            return CompactionResultDTO(
                success=outcome.success,
                tokens_before=tokens_before,
                tokens_after=tokens_after,
                summary=outcome.title or outcome.message,
                error=err_msg,
            )
        except Exception as exc:
            return CompactionResultDTO(
                success=False,
                tokens_before=0,
                tokens_after=0,
                summary="",
                error=str(exc),
            )

    async def get_rewind_points(self) -> list[RewindPointDTO]:
        """Fetch rollback candidates with git checkpoint statistics."""
        user_msgs: list[tuple[int, str]] = []
        if self.session and getattr(self.session, "messages", None):
            from johnston.core.domain.policies.messages import USER_EVENT_TYPE, is_ui_visible_user_message

            for i, m in enumerate(self.session.messages):
                if isinstance(m, dict) and m.get("type") == USER_EVENT_TYPE and is_ui_visible_user_message(m):
                    text = str(m.get("display_text") or m.get("text") or "")
                    user_msgs.append((i, text))

        proj_path = getattr(self.store, "project_path", None) if self.store else None
        try:
            entries = await get_rewind_git_stats(
                self.session_id,
                user_msgs,
                proj_path,
                session=self.session,
            )
        except Exception as exc:
            logger.debug("Failed to get rewind git stats: %s", exc)
            entries = []

        points: list[RewindPointDTO] = []
        for entry in entries:
            adds, dels, avail = _parse_rewind_stat_numbers(getattr(entry, "git_stats", ""))
            files = tuple(getattr(entry, "changed_files", ()))
            points.append(
                RewindPointDTO(
                    index=entry.index,
                    text=entry.text,
                    insertions=adds,
                    deletions=dels,
                    changed_files=files,
                    is_checkpoint_available=avail,
                )
            )
        return points

    def get_skills(self) -> list[SkillDTO]:
        """List available skills as SkillDTO."""
        sm = get_skill_manager()
        skills = sm.list_skills(include_hidden=True)
        result: list[SkillDTO] = []
        for s in skills:
            scope = getattr(s, "scope", None)
            scope_str = scope.value if hasattr(scope, "value") else str(scope or "global").lower()
            is_proj = scope_str == "project"
            result.append(
                SkillDTO(
                    name=getattr(s, "name", ""),
                    description=getattr(s, "description", "") or "",
                    path=getattr(s, "location", "") or getattr(s, "path", ""),
                    enabled=not getattr(s, "hidden", False),
                    is_project=is_proj,
                    scope=scope_str,
                )
            )
        return result

    def toggle_skill(self, name: str) -> bool:
        """Toggle hidden state of a skill, returning the new hidden state."""
        sm = get_skill_manager()
        return sm.toggle_hidden(name)

    def toggle_sandbox(self) -> bool:
        """Toggle shell command sandbox enforcement; saves config and returns new state."""
        from johnston.core.infrastructure.config.config_helpers import save_sandbox_config

        new_val = not bool(self.sandbox)
        self.sandbox = new_val
        if self.agent and hasattr(self.agent, "sandbox_enabled"):
            self.agent.sandbox_enabled = new_val
        try:
            save_sandbox_config(new_val)
        except Exception:
            pass
        return new_val

    def get_rules(self) -> list[RuleDTO]:
        """List active rules via RulesManager as RuleDTO."""
        rm = RulesManager.get_instance()
        rule_defs = rm.load_rules()
        result: list[RuleDTO] = []
        for r in rule_defs:
            content = r.content or ""
            preview = (content[:100] + "...") if len(content) > 100 else content
            result.append(
                RuleDTO(
                    title=r.name,
                    path=getattr(r, "path", ""),
                    content_preview=preview,
                    scope=r.source,
                )
            )
        return result

    def get_model_info(self, provider_key: str, model_name: str) -> ModelInfoDTO:
        """Get model details (display name, vision, thinking, context) as ModelInfoDTO."""
        from johnston.core.domain.policies.models_catalog import catalog

        clean_name = (
            catalog.get_model_display_name(provider_key, model_name)
            if hasattr(catalog, "get_model_display_name")
            else model_name
        )
        has_vis = catalog.has_vision(provider_key, model_name) if hasattr(catalog, "has_vision") else False
        ctx_limit = catalog.get_context_limit(provider_key, model_name) if hasattr(catalog, "get_context_limit") else 0
        has_thinking = any(term in model_name.lower() for term in ("thinking", "reasoner", "r1", "claude-3-7"))

        return ModelInfoDTO(
            name=model_name,
            display_name=clean_name or model_name,
            provider=provider_key,
            context_window=ctx_limit,
            supports_vision=has_vis,
            supports_thinking=has_thinking,
        )

    def get_providers(self) -> list[ProviderDTO]:
        """List configured/available providers and their models as ProviderDTO."""
        import os

        from johnston.core.domain.policies.models_catalog import catalog
        from johnston.core.infrastructure.platform.paths import CONFIG_DIR
        from johnston.core.infrastructure.platform.platform_utils import cached_json_read

        providers_dict = self.pm.load_providers(include_disabled=True) if hasattr(self.pm, "load_providers") else {}
        result: list[ProviderDTO] = []

        for pkey, info in providers_dict.items():
            p_def = self.pm.load_provider_def(pkey) if hasattr(self.pm, "load_provider_def") else None
            needs_key = self.pm.provider_needs_key(pkey, p_def) if (p_def and hasattr(self.pm, "provider_needs_key")) else True
            api_key = self.pm.get_api_key(pkey) if hasattr(self.pm, "get_api_key") else ""
            if not api_key and isinstance(info, dict):
                api_key = info.get("api_key", "")

            is_configured = (not needs_key) or bool(api_key)

            if p_def and getattr(p_def, "models", None):
                model_names = list(p_def.models)
            elif isinstance(info, dict) and info.get("models"):
                model_names = list(info.get("models"))
            elif p_def and hasattr(p_def, "models_fallback"):
                model_names = p_def.models_fallback()
            else:
                model_names = []

            if not model_names:
                try:
                    cache_path = os.path.join(CONFIG_DIR, "cache", f"models_{pkey}.json")
                    if os.path.exists(cache_path):
                        cdata = cached_json_read(cache_path, {})
                        if isinstance(cdata, dict):
                            c_models = cdata.get("models", [])
                            if isinstance(c_models, list) and c_models:
                                model_names = list(c_models)
                except Exception:
                    pass

            if not model_names:
                try:
                    cat_p = catalog.get_catalog_provider(pkey)
                    if isinstance(cat_p, dict):
                        cat_models = cat_p.get("models", [])
                        if isinstance(cat_models, list) and cat_models:
                            model_names = list(cat_models)
                except Exception:
                    pass

            models_dto: list[ModelInfoDTO] = [self.get_model_info(pkey, m_name) for m_name in model_names]

            is_active = pkey == self.provider
            is_disabled = (
                not getattr(p_def, "enabled", True)
                if p_def
                else (isinstance(info, dict) and not info.get("enabled", True))
            )
            p_name_raw = getattr(p_def, "name", None)
            disp_name = (
                str(p_name_raw)
                if isinstance(p_name_raw, str) and p_name_raw.strip()
                else (info.get("name") if isinstance(info, dict) and isinstance(info.get("name"), str) else pkey)
            ) or pkey
            result.append(
                ProviderDTO(
                    name=disp_name,
                    is_configured=is_configured,
                    models=models_dto,
                    key=pkey,
                    is_active=is_active,
                    is_disabled=is_disabled,
                )
            )
        return result

    def get_workspace_roots(self) -> list[WorkspaceRootDTO]:
        """Fetch workspace roots as WorkspaceRootDTO."""
        from johnston.core.application.permission.interactor import get_root_scope
        from johnston.core.application.permission.permission_manager import PermissionManager

        pm = getattr(self, "perm_manager", None) or PermissionManager.get_instance()
        roots = pm.get_workspace_roots()
        return [WorkspaceRootDTO(path=r, scope=get_root_scope(r)) for r in roots]

    def add_workspace_root(self, path: str, scope: str = "session") -> None:
        """Add a workspace root path."""
        from johnston.core.application.permission.interactor import add_workspace_root

        add_workspace_root(path, scope=scope)

    def remove_workspace_root(self, path: str) -> bool:
        """Remove a workspace root path."""
        from johnston.core.application.permission.interactor import remove_workspace_root

        return remove_workspace_root(path)

    def get_root_scope(self, path: str) -> str:
        """Get the permission scope for a workspace root path."""
        from johnston.core.application.permission.interactor import get_root_scope

        return get_root_scope(path)

    @staticmethod
    def build_permission_options(
        tool_name: str, args: dict[str, Any] | None = None, server_name: str | None = None
    ) -> tuple[list[tuple[str, str]], str]:
        """Build permission choice options and suggested pattern for confirmation dialogs."""
        from johnston.core.application.permission.interactor import build_permission_options

        return build_permission_options(tool_name, args, server_name)

    def list_worktrees(self, project_dir: str | None = None) -> list[WorktreeDTO]:
        """List git branches and worktrees as WorktreeDTO."""
        import os

        from johnston.core.infrastructure.runtime.git_worktree import GitWorktreeManager

        pdir = project_dir or getattr(self.store, "project_path", None) or os.getcwd()
        raw_items = GitWorktreeManager.list_branches_and_worktrees(pdir)
        result: list[WorktreeDTO] = []
        for it in raw_items:
            result.append(
                WorktreeDTO(
                    name=it.get("name", ""),
                    is_current=bool(it.get("is_current", False)),
                    is_worktree=bool(it.get("is_worktree", False)),
                    is_root=bool(it.get("is_root", False)),
                    path=it.get("path", ""),
                )
            )
        return result

    async def list_worktrees_async(self, project_dir: str | None = None) -> list[WorktreeDTO]:
        """Async variant of list_worktrees."""
        import asyncio

        return await asyncio.to_thread(self.list_worktrees, project_dir)

    def create_worktree(
        self,
        arg1: str = "",
        arg2: str | None = None,
        base_branch: str = "HEAD",
        branch_name: str | None = None,
        project_dir: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Create a git worktree."""
        import os

        from johnston.core.infrastructure.runtime.git_worktree import GitWorktreeManager

        if branch_name is not None:
            pdir = project_dir or getattr(self.store, "project_path", None) or os.getcwd()
            bname = branch_name
        elif arg2 is not None:
            # Called with two positional arguments (pdir, branch) or (branch, pdir)
            if os.path.exists(arg1) or "/" in arg1 or "\\" in arg1:
                pdir, bname = arg1, arg2
            elif os.path.exists(arg2) or "/" in arg2 or "\\" in arg2:
                bname, pdir = arg1, arg2
            else:
                pdir, bname = arg1, arg2
        else:
            pdir = getattr(self.store, "project_path", None) or os.getcwd()
            bname = arg1

        return GitWorktreeManager.create_worktree(pdir, bname, base_branch=base_branch)

    async def create_worktree_async(
        self,
        arg1: str = "",
        arg2: str | None = None,
        base_branch: str = "HEAD",
        branch_name: str | None = None,
        project_dir: str | None = None,
    ) -> tuple[str | None, str | None]:
        """Async variant of create_worktree."""
        import asyncio

        return await asyncio.to_thread(
            self.create_worktree, arg1, arg2, base_branch=base_branch, branch_name=branch_name, project_dir=project_dir
        )

    def check_merge_conflicts(
        self,
        arg1: str = "",
        arg2: str = "",
        arg3: str | None = None,
        source: str | None = None,
        target: str | None = None,
        project_dir: str | None = None,
    ) -> tuple[bool, list[str]]:
        """Check for merge conflicts between source and target."""
        import os

        from johnston.core.infrastructure.runtime.git_worktree import GitWorktreeManager

        if source is not None and target is not None:
            pdir = project_dir or getattr(self.store, "project_path", None) or os.getcwd()
            s, t = source, target
        elif arg3 is not None:
            # Called as (pdir, source, target) or (source, target, pdir)
            if os.path.exists(arg1) or "/" in arg1 or "\\" in arg1:
                pdir, s, t = arg1, arg2, arg3
            else:
                s, t, pdir = arg1, arg2, arg3
        else:
            pdir = getattr(self.store, "project_path", None) or os.getcwd()
            s, t = arg1, arg2

        return GitWorktreeManager.check_merge_conflicts(pdir, s, t)

    async def check_merge_conflicts_async(
        self,
        arg1: str = "",
        arg2: str = "",
        arg3: str | None = None,
        source: str | None = None,
        target: str | None = None,
        project_dir: str | None = None,
    ) -> tuple[bool, list[str]]:
        """Async variant of check_merge_conflicts."""
        import asyncio

        return await asyncio.to_thread(
            self.check_merge_conflicts, arg1, arg2, arg3, source=source, target=target, project_dir=project_dir
        )

    def merge_branch(
        self,
        arg1: str = "",
        arg2: str = "",
        arg3: str | None = None,
        source: str | None = None,
        target: str | None = None,
        project_dir: str | None = None,
    ) -> tuple[bool, str]:
        """Merge source into target branch."""
        import os

        from johnston.core.infrastructure.runtime.git_worktree import GitWorktreeManager

        if source is not None and target is not None:
            pdir = project_dir or getattr(self.store, "project_path", None) or os.getcwd()
            s, t = source, target
        elif arg3 is not None:
            if os.path.exists(arg1) or "/" in arg1 or "\\" in arg1:
                pdir, s, t = arg1, arg2, arg3
            else:
                s, t, pdir = arg1, arg2, arg3
        else:
            pdir = getattr(self.store, "project_path", None) or os.getcwd()
            s, t = arg1, arg2

        return GitWorktreeManager.merge_branch(pdir, s, t)

    async def merge_branch_async(
        self,
        arg1: str = "",
        arg2: str = "",
        arg3: str | None = None,
        source: str | None = None,
        target: str | None = None,
        project_dir: str | None = None,
    ) -> tuple[bool, str]:
        """Async variant of merge_branch."""
        import asyncio

        return await asyncio.to_thread(
            self.merge_branch, arg1, arg2, arg3, source=source, target=target, project_dir=project_dir
        )

    def remove_worktree(
        self, wt_path: str, branch_name: str = "", project_dir: str | None = None, delete_branch: bool = False
    ) -> bool:
        """Remove a worktree."""
        import os

        from johnston.core.infrastructure.runtime.git_worktree import GitWorktreeManager

        pdir = project_dir or getattr(self.store, "project_path", None) or os.getcwd()
        return GitWorktreeManager.remove_worktree(pdir, wt_path, branch_name=branch_name, delete_branch=delete_branch)

    async def remove_worktree_async(
        self, wt_path: str, branch_name: str = "", project_dir: str | None = None, delete_branch: bool = False
    ) -> bool:
        """Async variant of remove_worktree."""
        import asyncio

        return await asyncio.to_thread(self.remove_worktree, wt_path, branch_name, project_dir, delete_branch)

    def get_tasks(self, kind: str = "shell", session_id: str | None = None) -> list[TaskDTO]:
        """List active background tasks as TaskDTO."""
        from johnston.core.infrastructure.tasks.manage import extract_task_status_details

        tm = getattr(self, "task_manager", None)
        if not tm:
            return []

        all_tasks = tm.list(kind=kind) if hasattr(tm, "list") else list(tm)
        target_sid = session_id or self.session_id

        result: list[TaskDTO] = []
        for t in all_tasks:
            if target_sid and getattr(t, "session_id", None) and getattr(t, "session_id", None) != target_sid:
                continue
            if not getattr(t, "is_background", False):
                continue
            status, dur = extract_task_status_details(t)
            running = getattr(t, "is_running", False)
            if status == "running":
                badge = dur if dur and dur != "-" else "running..."
            elif status == "killed":
                badge = "killed"
            elif status == "timeout":
                badge = "timeout"
            elif status.startswith("exit:"):
                code = status.split(":", 1)[1]
                dur_suffix = f" • {dur}" if dur and dur != "-" else ""
                badge = f"exit {code}{dur_suffix}"
            else:
                badge = status or "done"

            tid = getattr(t, "task_id", getattr(t, "id", ""))
            raw_ca = getattr(t, "created_at", 0.0)
            try:
                ca = float(raw_ca) if isinstance(raw_ca, (int, float, str)) and not isinstance(raw_ca, bool) else 0.0
            except (ValueError, TypeError):
                ca = 0.0
            result.append(
                TaskDTO(
                    task_id=str(tid),
                    command=getattr(t, "command", ""),
                    status="RUNNING" if running else "FINISHED",
                    returncode=getattr(t, "returncode", None),
                    log_path=getattr(t, "log_path", ""),
                    is_running=running,
                    created_at=ca,
                    progress_badge=badge,
                )
            )
        return result

    def get_task(self, task_id: str) -> Any | None:
        """Get live task object by ID (for console logs)."""
        tm = getattr(self, "task_manager", None)
        if not tm:
            return None
        if hasattr(tm, "get"):
            return tm.get(task_id)
        for t in tm:
            if getattr(t, "task_id", getattr(t, "id", None)) == task_id:
                return t
        return None

    async def kill_task(self, task_id: str) -> bool:
        """Kill a running background task by ID."""
        import inspect

        t = self.get_task(task_id)
        if t and getattr(t, "is_running", False):
            res = t.kill()
            if inspect.isawaitable(res):
                await res
            return True
        return False

    async def kill_subagent(self, session_id: str, app: Any = None) -> bool:
        """Kill a running subagent session by ID."""
        from johnston.core.application.session.facade import kill_subagent, list_subagent_sessions

        sessions = list_subagent_sessions(parent_id=self.session_id, app=app)
        for s in sessions:
            if getattr(s, "id", "") == session_id:
                kill_subagent(s, app)
                return True
        # If not found under current session_id, check all subagent sessions
        all_sessions = list_subagent_sessions(parent_id=None, app=app)
        for s in all_sessions:
            if getattr(s, "id", "") == session_id:
                kill_subagent(s, app)
                return True
        return False

    def list_subagent_sessions(self, parent_id: str | None = None) -> list[Any]:
        """List subagent sessions scoped to parent_id."""
        from johnston.core.application.session.facade import list_subagent_sessions

        pid = parent_id if parent_id is not None else self.session_id
        return list_subagent_sessions(parent_id=pid, app=getattr(self, "app", None))

    def get_config_dir(self) -> str:
        """Return the core configuration directory path."""
        from johnston.core.infrastructure.platform.paths import CONFIG_DIR

        return CONFIG_DIR

    def get_git_state(self) -> GitStateDTO:
        """Get current repository git state as GitStateDTO."""
        branch = get_branch_info()
        diff_metrics = get_diff_metrics() if callable(get_diff_metrics) else None
        ins = diff_metrics.insertions if diff_metrics else 0
        dels = diff_metrics.deletions if diff_metrics else 0
        diff_stat = get_diff_stats() if callable(get_diff_stats) else ""
        if (not ins and not dels) and diff_stat:
            adds_p, dels_p, _ = _parse_rewind_stat_numbers(diff_stat)
            ins, dels = adds_p, dels_p

        is_dirty = bool(ins or dels)
        changed_files = 0

        try:
            res = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True,
                text=True,
                timeout=2,
            )
            if res.returncode == 0:
                lines = [ln for ln in res.stdout.splitlines() if ln.strip()]
                changed_files = len(lines)
                is_dirty = changed_files > 0
            elif is_dirty:
                changed_files = 1
        except Exception:
            if is_dirty:
                changed_files = 1

        return GitStateDTO(
            branch=branch,
            is_dirty=is_dirty,
            changed_files=changed_files,
            insertions=ins,
            deletions=dels,
        )
