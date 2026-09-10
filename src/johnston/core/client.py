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
    ToolCallDTO,
    TurnCompletedDTO,
    parse_event_dto,
)
from johnston.core.infrastructure.platform.git_metrics import get_branch_info, get_diff_stats
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
    ) -> None:
        self.pm = pm if pm is not None else ProviderManager()
        self.store = store if store is not None else SessionStore.get_instance()
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
            self.model = self.pm.get_provider_model(self.provider) or ""
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
            if self.model and hasattr(self.agent, "model"):
                self.agent.model = self.model
            if self.effort and hasattr(self.agent, "thinking_effort"):
                norm_effort = self.effort.strip().lower()
                self.agent.thinking_effort = norm_effort
                if hasattr(self.agent, "reasoning_effort"):
                    self.agent.reasoning_effort = norm_effort
            if self.sandbox is not None and hasattr(self.agent, "sandbox_enabled"):
                self.agent.sandbox_enabled = self.sandbox
            if self.branch and hasattr(self.agent, "worktree_branch"):
                self.agent.worktree_branch = self.branch

            if self.role:
                try:
                    apply_role(self.agent, self.role, mode=self.mode)
                except Exception:
                    logger.debug("Failed to apply role %s to agent", self.role, exc_info=True)

        # Session initialization
        self.session: Any = None
        self.session_id: str = session_id or ""
        if self.store is not None:
            if session_id:
                if hasattr(self.store, "get"):
                    self.session = self.store.get(session_id)
                if self.session is None and hasattr(self.store, "create_main"):
                    self.session = self.store.create_main(session_id=session_id, role=self.role)
            else:
                if hasattr(self.store, "generate_session_id") and hasattr(self.store, "create_main"):
                    generated_id = self.store.generate_session_id()
                    self.session = self.store.create_main(session_id=generated_id, role=self.role)
                    self.session_id = generated_id

            if self.session is not None:
                if hasattr(self.session, "agent_history") and self.session.agent_history and self.agent:
                    if hasattr(self.agent, "history"):
                        self.agent.history = list(self.session.agent_history)
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
            if self.store and hasattr(self.store, "save"):
                try:
                    self.store.save(self.session)
                except Exception:
                    pass

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
            # Sync session agent history if available
            if self.session is not None and hasattr(self.agent, "history"):
                self.session.agent_history = list(self.agent.history)
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
            is_proj = (scope.value == "project") if hasattr(scope, "value") else (str(scope) == "project")
            result.append(
                SkillDTO(
                    name=s.name,
                    description=s.description,
                    path=getattr(s, "location", "") or getattr(s, "path", ""),
                    enabled=not getattr(s, "hidden", False),
                    is_project=is_proj,
                )
            )
        return result

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

    def get_providers(self) -> list[ProviderDTO]:
        """List configured/available providers and their models as ProviderDTO."""
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

            models_dto: list[ModelInfoDTO] = []
            for m_name in model_names:
                models_dto.append(
                    ModelInfoDTO(
                        name=m_name,
                        display_name=m_name,
                        provider=pkey,
                        context_window=0,
                        supports_vision=False,
                        supports_thinking=False,
                    )
                )

            result.append(
                ProviderDTO(
                    name=pkey,
                    is_configured=is_configured,
                    models=models_dto,
                )
            )
        return result

    def get_git_state(self) -> GitStateDTO:
        """Get current repository git state as GitStateDTO."""
        branch = get_branch_info()
        diff_stat = get_diff_stats()
        is_dirty = bool(diff_stat)
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
        )
