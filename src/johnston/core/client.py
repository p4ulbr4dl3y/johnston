"""Johnston client facade — in-process API for Johnston core.

Zero imports from textual or johnston.tui.
All methods exchange strongly-typed DTOs defined in johnston.core.dto.
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any, AsyncIterator

from johnston.core.application.generation.engine import ProviderReadyState
from johnston.core.application.provider.provider_manager import ProviderManager
from johnston.core.application.roles.apply import apply_role
from johnston.core.application.rules.rules import RulesManager
from johnston.core.application.skills.manager import get_skill_manager
from johnston.core.domain.policies.messages import (
    get_user_event_type,
    is_ui_visible_user_message,
    transcript_before_turn,
)
from johnston.core.domain.policies.models_catalog import catalog
from johnston.core.domain.policies.role_policy import AgentMode
from johnston.core.dto import (
    CompactionResultDTO,
    ContentDeltaDTO,
    ErrorEventDTO,
    FooterCacheDTO,
    GitStateDTO,
    MessageDTO,
    ModelInfoDTO,
    ProviderDTO,
    RewindPointDTO,
    RoleInfoDTO,
    RuleDTO,
    SessionDTO,
    SessionSnapshotDTO,
    SessionSummaryDTO,
    SkillDTO,
    StatusFooterDTO,
    StreamEventDTO,
    TaskDTO,
    ToolCallDTO,
    TurnCompletedDTO,
    WorkspaceRootDTO,
    WorktreeDTO,
    parse_event_dto,
)
from johnston.core.infrastructure.platform.paths import (
    IMAGE_EXTENSIONS,
    TEMP_IMAGES_DIR,
    THEMES_DIR,
    WORKTREES_DIR,
)
from johnston.core.infrastructure.platform.platform_utils import atomic_write_json, read_json
from johnston.core.infrastructure.runtime.git_utils import make_git_diff
from johnston.core.infrastructure.runtime.git_worktree import GitWorktreeManager
from johnston.core.infrastructure.runtime.lru import LruCache
from johnston.core.infrastructure.storage.session_store import SessionStore
from johnston.core.infrastructure.tasks.output import (
    is_spinner_line,
    process_carriage_returns_lines,
)

logger = logging.getLogger(__name__)

__all__ = [
    "FooterCacheDTO",
    "GitWorktreeManager",
    "IMAGE_EXTENSIONS",
    "JohnstonClient",
    "LruCache",
    "ModelInfoDTO",
    "ProviderDTO",
    "ProviderReadyState",
    "RoleInfoDTO",
    "SessionSnapshotDTO",
    "StatusFooterDTO",
    "TEMP_IMAGES_DIR",
    "THEMES_DIR",
    "WORKTREES_DIR",
    "aclose_tools",
    "active_mcp_server_count",
    "adopt_task_exception",
    "advance_generation_engine",
    "apply_execution_mode",
    "apply_permission_choice",
    "apply_role_to_agent",
    "atomic_write_json",
    "auto_title_session",
    "build_core_services",
    "build_prompt_builder",
    "cancel_running_subagents",
    "catalog",
    "clean_heuristic_title",
    "close_tools",
    "collect_current_tasks",
    "collect_task_summary",
    "configure_agent",
    "configure_permission_manager",
    "configure_role_registry",
    "cycle_execution_mode",
    "display_thinking_effort",
    "ensure_provider_ready",
    "estimate_tokens",
    "execute_shell_command",
    "extract_task_status_details",
    "filter_to_session",
    "format_background_notification",
    "format_context_tokens",
    "format_duration",
    "get_branch_info",
    "get_config_paths",
    "get_diff_stats",
    "get_effort_auto",
    "get_extract_task_status_details",
    "get_fork_base_max_len",
    "get_gen_engine",
    "get_git_worktree_manager",
    "get_ignore_dirs",
    "get_mcp_manager",
    "get_mcp_service",
    "get_permission_manager",
    "get_provider_actions",
    "get_provider_ready_state",
    "get_providers",
    "get_role_display_name",
    "get_role_registry",
    "get_session_actions",
    "get_settings",
    "get_skill_helpers",
    "get_skill_manager",
    "get_store",
    "get_user_event_type",
    "get_workspace_root",
    "install_asyncio_exception_handler",
    "is_builtin_tool",
    "is_spinner_line",
    "is_ui_visible_user_message",
    "is_windows",
    "kill_subagent",
    "list_branches_and_worktrees",
    "list_skills",
    "load_mcp_servers",
    "load_sandbox_config",
    "make_git_diff",
    "mcp_tool_is_known",
    "normalize_tool_name",
    "process_carriage_returns",
    "process_carriage_returns_lines",
    "providers_to_dtos",
    "read_json",
    "resolve_session_by_title",
    "resolve_subagent_from_toolcall",
    "save_sandbox_config",
    "stream_step_to_session_event",
    "strip_ansi",
    "sync_session_metrics",
    "transcript_before_turn",
    "worktrees_dir",
]

_LAZY_EXPORTS = {
    "get_rewind_git_stats": ("johnston.core.application.session.actions", "get_rewind_git_stats"),
    "compact_session": ("johnston.core.application.session.actions", "compact_session"),
    "get_branch_info": ("johnston.core.infrastructure.platform.git_metrics", "get_branch_info"),
    "get_changed_file_count": ("johnston.core.infrastructure.platform.git_metrics", "get_changed_file_count"),
    "get_diff_metrics": ("johnston.core.infrastructure.platform.git_metrics", "get_diff_metrics"),
    "get_diff_stats": ("johnston.core.infrastructure.platform.git_metrics", "get_diff_stats"),
}


def __getattr__(name: str) -> Any:
    if name in _LAZY_EXPORTS:
        mod_name, attr_name = _LAZY_EXPORTS[name]
        import importlib

        mod = importlib.import_module(mod_name)
        val = getattr(mod, attr_name)
        globals()[name] = val
        return val
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


def _resolve_symbol(name: str) -> Any:
    val = globals().get(name)
    if val is not None:
        return val
    return __getattr__(name)


EFFORT_AUTO = "auto"


def normalize_thinking_effort(value: str | None) -> str | None:
    from johnston.core.infrastructure.runtime.thinking_effort import normalize_thinking_effort as _norm

    return _norm(value)


def display_thinking_effort(value: str | None) -> str:
    from johnston.core.infrastructure.runtime.thinking_effort import display_thinking_effort as _disp

    return _disp(value)


def estimate_tokens(input_val: Any, model: str | None = None) -> int:
    """Estimate token count using core character-class-aware heuristic."""
    from johnston.core.infrastructure.runtime.token_util import estimate_tokens as _est

    return _est(input_val)


def format_context_tokens(tokens: int) -> str:
    """Format token count into human-readable compact string (e.g. '128k', '1M')."""
    from johnston.core.domain.policies.models_catalog import format_context_tokens as _fmt

    return _fmt(tokens)


def get_role_display_name(role_or_key: Any, project_dir: str | None = None) -> str:
    """Return human-readable role name for a key, entity, or role definition."""
    from johnston.core.application.roles.role_registry import get_role_display_name as _get_name

    return _get_name(role_or_key, project_dir=project_dir)


def get_settings(config_file: str | None = None, force_reload: bool = False) -> Any:
    """Return central application settings."""
    from johnston.core.infrastructure.config.settings import get_settings as _gs

    return _gs(config_file=config_file, force_reload=force_reload)


def ensure_provider_ready(pm: Any, agent: Any) -> Any:
    """Check provider connection and model configuration."""
    from johnston.core.application.generation.engine import ensure_provider_ready as _ensure

    return _ensure(pm, agent)


async def auto_title_session(agent: Any, session: Any, *, timeout: float | None = None) -> Any:
    """(async) Auto-generate a session title."""
    from johnston.core.application.session.auto_title import auto_title_session as _auto_title

    return await _auto_title(agent, session, timeout=timeout)


def sync_session_metrics(session: Any, agent: Any) -> Any:
    """Sync token/cost metrics from live agent onto session record."""
    from johnston.core.application.session.stream import sync_session_metrics as _sync

    return _sync(session, agent)


async def execute_shell_command(
    cmd: str,
    *,
    cwd: str | None = None,
    host: Any = None,
    session: Any = None,
    agent: Any = None,
) -> Any:
    """(async) Run a shell command through the core session executor."""
    from johnston.core.application.session.shell_executor import execute_shell_command as _exec

    return await _exec(cmd, cwd=cwd, host=host, session=session, agent=agent)


def extract_task_status_details(task: Any) -> tuple[str, str]:
    """Extract (status, duration_badge) from a task object."""
    from johnston.core.infrastructure.tasks.manage import extract_task_status_details as _extract

    return _extract(task)


def is_windows() -> bool:
    from johnston.core.infrastructure.platform.platform_utils import is_windows as _iw

    return _iw()


def process_carriage_returns(text: str) -> str:
    from johnston.core.infrastructure.tasks.output import process_carriage_returns as _pcr

    return _pcr(text)


def strip_ansi(text: str) -> str:
    from johnston.core.infrastructure.tasks.output import strip_ansi as _sa

    return _sa(text)


def kill_subagent(session: Any, app: Any = None) -> bool:
    from johnston.core.application.session.facade import kill_subagent as _kill

    return _kill(session, app)


def _get_store(app: Any = None) -> Any:
    from johnston.core.application.session.facade import _get_store as _gs

    return _gs(app)


def McpService(*args: Any, **kwargs: Any) -> Any:
    from johnston.core.application.mcp.mcp_service import McpService as _McpService

    return _McpService(*args, **kwargs)


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


class _CatalogProperty(property):
    """Descriptor providing both attribute and call access to the models catalog."""

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        from johnston.core.domain.policies.models_catalog import catalog as _cat

        return _cat


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
        app: Any | None = None,
    ) -> None:
        self.app = app
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
            # A caller-supplied agent (e.g. the interactive TUI) already carries
            # its execution mode. Do not flip it to HEADLESS just because the
            # client default applies — only role/model/effort settings are synced.
            agent_has_mode = getattr(agent, "mode", None) is not None or getattr(agent, "is_headless", None) is not None
            effective_mode = self.mode if agent_has_mode is False else getattr(agent, "mode", self.mode)
        elif self.provider and hasattr(self.pm, "create_agent_for_provider"):
            self.agent = self.pm.create_agent_for_provider(self.provider)
            effective_mode = self.mode
        else:
            self.agent = None
            effective_mode = self.mode

        if self.agent is not None:
            if self.role:
                try:
                    apply_role(self.agent, self.role, mode=effective_mode)
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
            last_msg = self.session.messages[-1] if self.session.messages else None
            is_dup = (
                isinstance(last_msg, dict)
                and (last_msg.get("role") == "user" or last_msg.get("type") == "user")
                and (last_msg.get("text") == prompt or last_msg.get("content") == prompt)
            )
            if not is_dup:
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
            outcome = await _resolve_symbol("compact_session")(
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
            entries = await _resolve_symbol("get_rewind_git_stats")(
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

        clean_name = (
            self.catalog.get_model_display_name(provider_key, model_name)
            if hasattr(self.catalog, "get_model_display_name")
            else model_name
        )
        has_vis = self.catalog.has_vision(provider_key, model_name) if hasattr(self.catalog, "has_vision") else False
        ctx_limit = self.catalog.get_context_limit(provider_key, model_name) if hasattr(self.catalog, "get_context_limit") else 0
        has_thinking = any(term in model_name.lower() for term in ("thinking", "reasoner", "r1", "claude-3-7"))

        return ModelInfoDTO(
            name=model_name,
            display_name=clean_name or model_name,
            provider=provider_key,
            context_window=ctx_limit,
            supports_vision=has_vis,
            supports_thinking=has_thinking,
        )

    def estimate_cost(self, provider_key: str, model_name: str, total_tokens: int) -> float:
        """Estimate token cost for provider/model."""

        if hasattr(self.catalog, "estimate_cost_from_totals"):
            return float(self.catalog.estimate_cost_from_totals(provider_key, model_name, total_tokens))
        return 0.0

    def get_providers(self) -> list[ProviderDTO]:
        """List configured/available providers and their models as ProviderDTO."""
        import os

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

            model_names = []
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
                    cat_p = self.catalog.get_catalog_provider(pkey)
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

    def kill_subagent_sync(self, session: Any, app: Any = None) -> bool:
        """Synchronously kill a subagent session."""
        from johnston.core.application.session.facade import kill_subagent

        target_app = app or getattr(self, "app", None)
        return kill_subagent(session, app=target_app)

    async def kill_subagent(self, session_id: Any, app: Any = None) -> bool:
        """Kill a running subagent session by ID or session object."""
        from johnston.core.application.session.facade import kill_subagent, list_subagent_sessions

        target_app = app or getattr(self, "app", None)
        if not isinstance(session_id, str):
            return kill_subagent(session_id, app=target_app, store=self.store)

        sessions = list_subagent_sessions(parent_id=self.session_id, app=target_app, store=self.store)
        for s in sessions:
            if getattr(s, "id", "") == session_id:
                kill_subagent(s, app=target_app, store=self.store)
                return True
        # If not found under current session_id, check all subagent sessions
        all_sessions = list_subagent_sessions(parent_id=None, app=target_app, store=self.store)
        for s in all_sessions:
            if getattr(s, "id", "") == session_id:
                kill_subagent(s, app=target_app, store=self.store)
                return True
        return False

    def list_subagent_sessions(self, parent_id: str | None = None) -> list[Any]:
        """List subagent sessions scoped to parent_id."""
        from johnston.core.application.session.facade import list_subagent_sessions

        pid = parent_id if parent_id is not None else self.session_id
        return list_subagent_sessions(parent_id=pid, app=getattr(self, "app", None), store=self.store)

    def get_config_dir(self) -> str:
        """Return the core configuration directory path."""
        from johnston.core.infrastructure.platform.paths import CONFIG_DIR

        return CONFIG_DIR

    def get_git_state(self) -> GitStateDTO:
        """Get current repository git state as GitStateDTO."""
        get_branch_fn = _resolve_symbol("get_branch_info")
        branch = get_branch_fn() if callable(get_branch_fn) else ""
        diff_metrics_fn = _resolve_symbol("get_diff_metrics")
        diff_metrics = diff_metrics_fn() if callable(diff_metrics_fn) else None
        ins = diff_metrics.insertions if diff_metrics else 0
        dels = diff_metrics.deletions if diff_metrics else 0
        diff_stats_fn = _resolve_symbol("get_diff_stats")
        diff_stat = diff_stats_fn() if callable(diff_stats_fn) else ""
        if (not ins and not dels) and diff_stat:
            adds_p, dels_p, _ = _parse_rewind_stat_numbers(diff_stat)
            ins, dels = adds_p, dels_p

        is_dirty = bool(ins or dels)
        changed_files = 0

        try:
            get_count_fn = _resolve_symbol("get_changed_file_count")
            changed_files = get_count_fn() if callable(get_count_fn) else 0
            if changed_files:
                is_dirty = True
        except Exception:
            if is_dirty:
                changed_files = 1

        if changed_files == 0 and is_dirty:
            changed_files = 1

        return GitStateDTO(
            branch=branch,
            is_dirty=is_dirty,
            changed_files=changed_files,
            insertions=ins,
            deletions=dels,
        )

    def get_thinking_effort(self) -> str:
        """Get current thinking effort for active provider and model."""
        provider_key = self.provider or (
            self.pm.get_active_provider_key() if hasattr(self.pm, "get_active_provider_key") else ""
        )
        model_name = getattr(self.agent, "model", "") or (
            self.pm.get_provider_model(provider_key) if hasattr(self.pm, "get_provider_model") else ""
        )
        effort = ""
        if hasattr(self.pm, "get_provider_thinking_effort"):
            effort = self.pm.get_provider_thinking_effort(provider_key, model_name)
        return effort or self.effort or EFFORT_AUTO

    def set_thinking_effort(self, effort: str, app: Any = None) -> None:
        """Persist thinking effort and update active agent."""
        provider_key = self.provider or (
            self.pm.get_active_provider_key() if hasattr(self.pm, "get_active_provider_key") else ""
        )
        model_name = getattr(self.agent, "model", "") or (
            self.pm.get_provider_model(provider_key) if hasattr(self.pm, "get_provider_model") else ""
        )
        if hasattr(self.pm, "set_provider_thinking_effort"):
            self.pm.set_provider_thinking_effort(provider_key, model_name, effort)
        self.effort = effort
        norm_effort = effort.strip().lower()
        if self.agent is not None:
            setattr(self.agent, "thinking_effort", norm_effort)
            setattr(self.agent, "reasoning_effort", norm_effort)
        if app is not None and hasattr(app, "agent") and app.agent is not None:
            setattr(app.agent, "thinking_effort", norm_effort)
            setattr(app.agent, "reasoning_effort", norm_effort)

    def resolve_session_by_title(
        self,
        title: str,
        parent_id: str | None = None,
        app: Any = None,
    ) -> Any | None:
        """Find a session by title or ID, scoped to parent_id first then globally."""
        from johnston.core.application.session.facade import resolve_session_by_title

        pid = parent_id if parent_id is not None else (self.session_id or None)
        found = resolve_session_by_title(title, parent_id=pid, app=app)
        if found is None and self.store is not None and hasattr(self.store, "find_session_by_title_or_id"):
            found = self.store.find_session_by_title_or_id(title, parent_id=pid)
            if found is None and pid:
                found = self.store.find_session_by_title_or_id(title)
        return found

    def get_checkpoint_diff(
        self,
        session_id: str,
        checkpoint_idx: int,
        project_path: str | None = None,
        scoped_files: list[str] | tuple[str, ...] | None = None,
    ) -> list[Any]:
        """Fetch diff items for a specific checkpoint."""
        from johnston.core.domain.ports.checkpoint import get_checkpoint_manager

        cm = get_checkpoint_manager()
        if not cm:
            return []
        pdir = project_path or getattr(self.store, "project_path", None)
        return cm.get_checkpoint_diff(
            session_id,
            checkpoint_idx,
            project_path=pdir,
            scoped_files=list(scoped_files) if scoped_files is not None else None,
        )

    def rewind_to(
        self,
        point_index: int,
        restore_code: bool = True,
        project_path: str | None = None,
    ) -> bool:
        """Rewind session history and optionally restore git checkpoint to point_index."""
        from johnston.core.application.session.actions import rewind_session

        user_msgs: list[tuple[int, str]] = []
        if self.session and getattr(self.session, "messages", None):
            from johnston.core.domain.policies.messages import USER_EVENT_TYPE, is_ui_visible_user_message

            for i, m in enumerate(self.session.messages):
                if isinstance(m, dict) and m.get("type") == USER_EVENT_TYPE and is_ui_visible_user_message(m):
                    text = str(m.get("display_text") or m.get("text") or "")
                    user_msgs.append((i, text))

        pdir = project_path or getattr(self.store, "project_path", None)

        def _save():
            if self.store and self.session and hasattr(self.store, "save"):
                try:
                    self.store.save(self.session)
                except Exception:
                    pass

        rewind_session(
            self.agent,
            self.session_id,
            pdir,
            user_msgs,
            point_index,
            restore_git=restore_code,
            session=self.session,
            rollback_ui=lambda _: None,
            load_text_into_input=lambda _: None,
            save_session_cb=_save,
            refresh_footer_cb=lambda: None,
            store=self.store,
            task_manager=self.task_manager,
        )
        return True

    def estimate_tokens(self, text: str | Any = "", model: str | None = None) -> int:
        """Estimate token count for text or structured payload."""
        if not isinstance(self, JohnstonClient):
            return estimate_tokens(self, model=model)
        return estimate_tokens(text, model=model)

    def format_context_tokens(self, tokens: int | None = None) -> str:
        """Format token count as a compact human-readable string (e.g. '128k', '1M')."""
        if not isinstance(self, JohnstonClient):
            return format_context_tokens(int(self))
        if tokens is None:
            return "0"
        return format_context_tokens(tokens)

    def get_role_display_name(self, role: str | None = None, project_dir: str | None = None) -> str:
        """Return human-readable role name for a key, entity, or role definition."""
        if not isinstance(self, JohnstonClient):
            return get_role_display_name(self, project_dir=project_dir or role)
        target_role = role if role is not None else getattr(self, "role", "worker")
        pdir = project_dir or (getattr(self.store, "project_path", None) if getattr(self, "store", None) else None)
        return get_role_display_name(target_role, project_dir=pdir)

    def get_settings(self: Any = None) -> Any:
        """Return central application settings."""
        return get_settings()

    @property
    def settings(self) -> Any:
        """Return central application settings."""
        return self.get_settings()

    @property
    def role_display_name(self) -> str:
        """Human-readable display name for the client's current role."""
        return self.get_role_display_name(self.role)

    def ensure_provider_ready(self, agent: Any = None, *args: Any) -> Any:
        """Check provider connection and model configuration."""
        if not isinstance(self, JohnstonClient):
            return ensure_provider_ready(self, agent)
        if args:
            return ensure_provider_ready(agent, args[0])
        target_agent = agent if agent is not None else self.agent
        return ensure_provider_ready(self.pm, target_agent)

    async def auto_title_session(self, session_id: str | Any = "", *args: Any, **kwargs: Any) -> Any:
        """Auto-generate and persist a concise title for the session."""
        if not isinstance(self, JohnstonClient):
            return await auto_title_session(self, session_id, **kwargs)

        if args:
            target_agent, sess = session_id, args[0]
        else:
            target_agent = self.agent
            target_sid = session_id or self.session_id
            sess = None
            if self.session and getattr(self.session, "id", "") == target_sid:
                sess = self.session
            elif not isinstance(target_sid, str):
                sess = target_sid
            elif self.store and hasattr(self.store, "get"):
                sess = self.store.get(target_sid)

        if sess is None:
            return None

        title = await auto_title_session(target_agent, sess, **kwargs)
        if self.store and hasattr(self.store, "save"):
            try:
                self.store.save(sess)
            except Exception:
                pass
        return title

    def sync_session_metrics(self, session_id: str | Any = "", *args: Any) -> Any:
        """Sync context/token metrics onto the session."""
        if not isinstance(self, JohnstonClient):
            return sync_session_metrics(self, session_id)

        if args:
            return sync_session_metrics(session_id, args[0])

        target_sid = session_id or self.session_id
        sess = None
        if self.session and getattr(self.session, "id", "") == target_sid:
            sess = self.session
        elif not isinstance(target_sid, str):
            sess = target_sid
        elif self.store and hasattr(self.store, "get"):
            sess = self.store.get(target_sid)

        if sess is not None and self.agent is not None:
            sync_session_metrics(sess, self.agent)
            if self.store and hasattr(self.store, "save"):
                try:
                    self.store.save(sess)
                except Exception:
                    pass
        return None

    async def execute_shell_command(
        self,
        cmd: str,
        cwd: str | None = None,
        *,
        host: Any | None = None,
        session: Any | None = None,
        agent: Any | None = None,
    ) -> Any:
        """Execute a shell command through core shell executor."""
        target_host = host if host is not None else getattr(self, "app", None)
        target_session = session if session is not None else self.session
        target_agent = agent if agent is not None else self.agent

        return await execute_shell_command(
            cmd,
            cwd=cwd,
            host=target_host,
            session=target_session,
            agent=target_agent,
        )

    extract_task_status_details = staticmethod(extract_task_status_details)

    @_CatalogProperty
    def catalog(self) -> Any:
        """Return global ModelsCatalog policy singleton."""
        from johnston.core.domain.policies.models_catalog import catalog as _cat

        return _cat

    def get_mcp_manager(self: Any = None, *args: Any, **kwargs: Any) -> Any:
        """Return the MCP manager instance."""
        from johnston.core.infrastructure.mcp import get_mcp_manager as _gmm

        return _gmm(*args, **kwargs)

    def get_gen_engine(self: Any = None) -> Any:
        """Return the generation engine components."""
        from johnston.core.application.generation.engine import get_gen_engine as _gge

        return _gge()

    def get_permission_manager(self: Any = None, session_id: str | None = None) -> Any:
        """Return the permission manager instance or singleton."""
        from johnston.core.application.permission.permission_manager import PermissionManager

        if isinstance(self, JohnstonClient) and getattr(self, "perm_manager", None) is not None:
            return self.perm_manager
        return PermissionManager.get_instance()

    def get_session_actions(self: Any = None) -> Any:
        """Return the session actions module."""
        import johnston.core.application.session.actions as actions

        return actions

    def cancel_running_subagents(self, parent_id: str | None = None) -> int:
        """Cancel running subagents and mark their sessions cancelled."""
        from johnston.core.application.session.subagent_service import SubagentService

        store = getattr(self, "store", None) if isinstance(self, JohnstonClient) else None
        return SubagentService.cancel_running_subagents(store, parent_id)

    def resolve_subagent_from_toolcall(
        self, tool: str | Any = "", args: dict[str, Any] | None = None, app: Any = None
    ) -> str | None:
        """Extract a subagent session ID from tool-call arguments."""
        from johnston.core.application.session.facade import resolve_subagent_from_toolcall as _resolve

        if not isinstance(self, JohnstonClient):
            real_tool = str(self)
            real_args = tool if isinstance(tool, dict) else (args or {})
            real_app = args if not isinstance(tool, dict) else app
            return _resolve(real_tool, real_args, app=real_app)
        target_app = app if app is not None else getattr(self, "app", None)
        return _resolve(tool, args or {}, app=target_app)

    def make_git_diff(
        self,
        old_str: str,
        new_str: str = "",
        file_path: str = "",
        *,
        fromfile: str | None = None,
        tofile: str | None = None,
        context: int = 3,
    ) -> str:
        """Generate a unified diff between old and new strings."""
        from johnston.core.infrastructure.runtime.git_utils import make_git_diff as _mgd

        if not isinstance(self, JohnstonClient):
            f_label = fromfile or file_path or "file"
            t_label = tofile or file_path or "file"
            return _mgd(self, old_str, fromfile=f_label, tofile=t_label, context=context)
        f_label = fromfile or file_path or "file"
        t_label = tofile or file_path or "file"
        return _mgd(old_str, new_str, fromfile=f_label, tofile=t_label, context=context)

    def read_json(self, path: str | Any = "", default: Any = None) -> Any:
        """Read a JSON file safely, returning default if missing or invalid."""
        from johnston.core.infrastructure.platform.platform_utils import read_json as _read_json

        if not isinstance(self, JohnstonClient):
            return _read_json(self, default=path if path != "" else default)
        return _read_json(path, default=default)

    def atomic_write_json(self, path: str | Any, data: Any = None, indent: int = 2) -> None:
        """Atomically write data to a JSON file."""
        from johnston.core.infrastructure.platform.platform_utils import atomic_write_json as _atomic_write_json

        if not isinstance(self, JohnstonClient):
            _atomic_write_json(self, path, indent=data if isinstance(data, int) else indent)
            return
        _atomic_write_json(path, data, indent=indent)



# =====================================================================
# Canonical Core Public Facade Functions (Client API)
# =====================================================================


def get_branch_info(cwd: str | None = None) -> Any:
    """Detect the current git branch (core git metrics helper)."""
    from johnston.core.infrastructure.platform.git_metrics import get_branch_info as _f

    return _f(cwd)


def get_diff_stats(cwd: str | None = None) -> Any:
    """Compute '+add/-del' diff stats vs HEAD (core git metrics helper)."""
    from johnston.core.infrastructure.platform.git_metrics import get_diff_stats as _f

    return _f(cwd)


def get_mcp_manager() -> Any:
    """Singleton MCP manager (core infrastructure)."""
    from johnston.core.infrastructure import mcp as _m

    return _m.get_mcp_manager()


def worktrees_dir() -> str:
    """Resolve the worktrees directory live from core paths (test-overridable)."""
    import johnston.core.infrastructure.platform.paths as _m
    return getattr(_m, "WORKTREES_DIR", "") or ""


def get_git_worktree_manager() -> type[GitWorktreeManager]:
    """Core GitWorktreeManager class (lazy, for feature/async detection)."""
    return GitWorktreeManager


def get_ignore_dirs() -> list[str]:
    """Default git-ignore directory names (core defaults)."""
    from johnston.core.domain.defaults.git_excludes import DEFAULT_IGNORE_DIRS as _f
    return _f


def list_branches_and_worktrees(project_dir: str) -> Any:
    """List git branches and worktrees (core git worktree helper)."""
    return GitWorktreeManager.list_branches_and_worktrees(project_dir)


def collect_task_summary(app: Any, session_id: str | None = None) -> tuple[list[Any], list[Any]]:
    """Return (shell_tasks, subagent_sessions) for the current app/session."""
    from johnston.core.infrastructure.runtime.task_collection import collect_current_tasks as _collect
    tasks = _collect(app, session_id)
    return tasks.shell_tasks, tasks.subagent_tasks


def collect_current_tasks(app: Any, session_id: str | None = None) -> Any:
    """Collect shell/subagent task state for the status footer (core helper)."""
    from johnston.core.infrastructure.runtime.task_collection import collect_current_tasks as _f
    return _f(app, session_id)


def filter_to_session(tasks: Any, session_id: Any) -> Any:
    """Filter tasks to the given session scope (core task manager helper)."""
    from johnston.core.infrastructure.tasks.manage import filter_to_session as _f
    return _f(tasks, session_id)


def format_duration(seconds: float | int | None) -> str:
    """Format a duration as a concise string (core task helper)."""
    from johnston.core.infrastructure.tasks.manage import format_duration as _f
    return _f(seconds)


def get_extract_task_status_details() -> Any:
    """Core task status extraction helper."""
    from johnston.core.client import extract_task_status_details as _f
    return _f


def resolve_subagent_from_toolcall(tool: str, args: dict[str, Any], app: Any = None) -> str | None:
    """Resolve a subagent session id from a tool call (used by tool widgets)."""
    from johnston.core.application.session.facade import resolve_subagent_from_toolcall as _r
    return _r(tool, args, app)


def resolve_session_by_title(identifier: str, parent_id: str | None = None, app: Any = None) -> Any:
    """Resolve a session by title or id."""
    from johnston.core.application.session.facade import resolve_session_by_title as _r
    return _r(identifier, parent_id=parent_id, app=app)


def cancel_running_subagents(sm: Any, parent_id: str | None = None) -> int:
    """Cancel running subagent sessions (used on app shutdown / rewind)."""
    from johnston.core.application.session.stream import cancel_running_subagents as _c
    try:
        return _c(sm, parent_id)
    except Exception:
        return 0


def clean_heuristic_title(text: str, max_len: int = 60) -> str:
    """Clean a heuristic session title (core auto_title helper)."""
    from johnston.core.application.session.auto_title import clean_heuristic_title as _f
    return _f(text, max_len=max_len)


def get_session_actions() -> dict[str, Any]:
    """Core session action helpers (new/compact/rewind/plan/diff)."""
    from johnston.core.application.session.actions import (
        _touched_files,
        compact_session,
        find_selected_user_message,
        get_rewind_git_stats,
        get_session_diff,
        new_session,
        restore_plan_from_messages,
        rewind_session,
        truncate_agent_history,
    )
    return dict(
        _touched_files=_touched_files,
        compact_session=compact_session,
        find_selected_user_message=find_selected_user_message,
        get_rewind_git_stats=get_rewind_git_stats,
        get_session_diff=get_session_diff,
        new_session=new_session,
        restore_plan_from_messages=restore_plan_from_messages,
        rewind_session=rewind_session,
        truncate_agent_history=truncate_agent_history,
    )


def get_fork_base_max_len() -> int:
    """Max length for fork titles (core session naming policy)."""
    from johnston.core.domain.policies.session_naming import FORK_BASE_MAX_LEN as _f
    return _f


def get_permission_manager() -> Any:
    """Shortcut for core PermissionManager singleton."""
    from johnston.core.application.permission.permission_manager import PermissionManager
    return PermissionManager


def configure_permission_manager(tool_name_normalizer: Any) -> None:
    """Configure the global PermissionManager singleton."""
    from johnston.core.application.permission.permission_manager import PermissionManager
    PermissionManager.configure_instance(tool_name_normalizer=tool_name_normalizer)


def apply_execution_mode(app: Any, mode: str) -> None:
    """Set the permission execution mode from the --mode CLI flag."""
    from johnston.core.application.permission.permission_manager import PermissionManager
    from johnston.core.domain.policies.permission_policy import ExecutionMode
    try:
        PermissionManager.get_instance().set_session_mode(ExecutionMode(mode.lower()))
    except Exception:
        pass


def cycle_execution_mode() -> Any:
    """Cycle permission execution mode: review -> edits -> yolo -> review."""
    from johnston.core.application.permission.interactor import cycle_execution_mode as _f
    return _f()


def apply_permission_choice(choice: Any, permission_name: Any) -> Any:
    """Apply a permission choice onto the permission manager singleton."""
    from johnston.core.application.permission.interactor import apply_permission_choice as _f
    return _f(choice, permission_name)


def list_skills(*, include_hidden: bool = False) -> Any:
    """List skills via core skill manager (lazy import)."""
    from johnston.core.application.skills.manager import get_skill_manager
    return get_skill_manager().list_skills(include_hidden=include_hidden)


def get_skill_helpers() -> dict[str, Any]:
    """Core skill helper functions (homoglyph normalize, skill resolve)."""
    from johnston.core.application.skills.inject import (
        load_skill_blocks,
        normalize_homoglyphs,
        resolve_skills,
    )
    return dict(
        load_skill_blocks=load_skill_blocks,
        normalize_homoglyphs=normalize_homoglyphs,
        resolve_skills=resolve_skills,
    )


def get_store(app: Any = None) -> Any:
    """Resolve the session store (core client facade, live lookup)."""
    from johnston.core.client import _get_store as _f
    return _f(app)


def get_workspace_root() -> str:
    """Current workspace root path from core."""
    from johnston.core.infrastructure.platform import paths
    return paths.workspace_root()


def get_config_paths() -> Any:
    """Core platform path constants (CONFIG_DIR, PROMPT_HISTORY_FILE, ...)."""
    from johnston.core.infrastructure.platform import paths as _paths
    return _paths


def install_asyncio_exception_handler() -> None:
    """Install the global asyncio exception handler."""
    from johnston.core.infrastructure.platform.logging_setup import install_asyncio_exception_handler as _f
    _f()


def adopt_task_exception(task: Any) -> None:
    """Attach an exception handler to a tracked task."""
    from johnston.core.infrastructure.platform.logging_setup import adopt_task_exception as _f
    _f(task)


def load_sandbox_config() -> bool:
    """Load the sandbox default from core config."""
    from johnston.core.infrastructure.config.config_helpers import load_sandbox_config as _f
    return _f()


def save_sandbox_config(enabled: bool) -> None:
    """Persist the sandbox default (core config helper, live lookup)."""
    import johnston.core.infrastructure.config.config_helpers as _m
    _m.save_sandbox_config(enabled)


def normalize_tool_name(name: str) -> str:
    """Normalize tool name for display and lookup."""
    from johnston.core.infrastructure.runtime.tool_name import normalize_tool_name as _f
    return _f(name)


def close_tools() -> None:
    """Close all registered tool instances (used on app shutdown)."""
    import asyncio

    from johnston.core.tools.registry import aclose_tools as _aclose_tools
    asyncio.run(_aclose_tools())


def aclose_tools() -> Any:
    """Core tool registry async close (live lookup)."""
    from johnston.core.tools.registry import aclose_tools as _f
    return _f()


def format_background_notification(*args: Any, **kwargs: Any) -> Any:
    """Format a background-task completion notification (core tools base)."""
    from johnston.core.tools.base import format_background_notification as _f
    return _f(*args, **kwargs)


def is_builtin_tool(name: str) -> bool:
    """Whether a tool name is registered in the core tool registry."""
    from johnston.core.tools.registry import REGISTRY as _r
    return name in _r


def load_mcp_servers() -> Any:
    """Load MCP servers via core MCP manager."""
    from johnston.core.infrastructure import mcp as mcp_mod
    return mcp_mod.get_mcp_manager().load_servers()


def active_mcp_server_count(servers: list[Any]) -> int:
    """Number of currently-active MCP servers among servers."""
    from johnston.core.infrastructure import mcp as mcp_mod
    try:
        fn = getattr(mcp_mod.get_mcp_manager(), "active_server_count", None)
        if callable(fn):
            return fn(servers) or 0
    except Exception:
        pass
    return 0


def mcp_tool_is_known(name: str) -> bool:
    """Whether a tool name belongs to a known MCP server."""
    from johnston.core.infrastructure.mcp import mcp_tool_is_known as _f
    return _f(name)


def get_mcp_service(*args: Any, **kwargs: Any) -> Any:
    """Instantiate core McpService."""
    from johnston.core.client import McpService as _f
    return _f(*args, **kwargs)


def get_role_registry() -> Any:
    """Core RoleRegistry class (singleton access via get_instance())."""
    from johnston.core.application.roles.role_registry import RoleRegistry
    return RoleRegistry


def configure_role_registry(tool_name_normalizer: Any) -> None:
    """Configure the global RoleRegistry singleton."""
    from johnston.core.application.roles.role_registry import RoleRegistry
    RoleRegistry._instance = RoleRegistry(tool_name_normalizer=tool_name_normalizer)


def apply_role_to_agent(app: Any, role: Any) -> None:
    """Apply CLI-selected role to the active agent."""
    from johnston.core.application.roles.apply import apply_role as _apply_role
    try:
        _apply_role(app.agent, role, is_subagent=False)
        app.role = role
    except Exception:
        pass


def build_core_services(app: Any) -> None:
    """Create provider manager, session store, task manager, agent and client facade."""
    from johnston.core.application.provider.provider_manager import ProviderManager
    from johnston.core.domain.policies.role_policy import AgentMode
    from johnston.core.infrastructure.storage.session_store import SessionStore
    from johnston.core.infrastructure.tasks.manager import TaskManager

    app.pm = ProviderManager()
    app.sm = SessionStore()
    app.task_manager = TaskManager()
    app._subagent_tools = {}
    app._background_shell_widgets = {}
    app._foreground_shell_tasks = {}
    app.agent = app.pm.create_active_agent()
    app.role = getattr(app.agent, "role", "worker") if app.agent else "worker"
    if app.agent:
        app.agent.app = app
        app.agent.mode = AgentMode.INTERACTIVE
        app.agent.is_headless = False
        app.agent.is_subagent = False
    app.client = JohnstonClient(
        pm=app.pm,
        store=app.sm,
        agent=app.agent,
        task_manager=app.task_manager,
        app=app,
    )
    app.selection_copy_active = False
    app.message_queue = []
    app.is_generating = False
    app._is_compacting = False
    app.is_compacting = False
    app._background_tasks = set()


def build_prompt_builder(
    base_system_prompt: Any,
    base_tools: Any,
    *,
    role: str = "worker",
    is_subagent: bool = False,
    subagent_schema: Any = None,
) -> Any:
    """Instantiate the core PromptBuilder bound to an agent prompt/tools."""
    import johnston.core.application.generation.prompt_builder as _m
    return _m.PromptBuilder(
        base_system_prompt,
        base_tools,
        role=role,
        is_subagent=is_subagent,
        subagent_schema=subagent_schema,
    )


def advance_generation_engine(provider_manager: Any, agent: Any) -> Any:
    """(async) Ensure the active provider is ready for generation (core engine)."""
    from johnston.core.application.generation.engine import ensure_provider_ready as _f
    return _f(provider_manager, agent)


def get_provider_ready_state() -> Any:
    """Provider readiness enum from the core generation engine."""
    from johnston.core.application.generation.engine import ProviderReadyState as _f
    return _f


def stream_step_to_session_event(
    step: Any, text_accumulator: Any = None, *, from_stream_step: bool = False
) -> Any:
    """Canonicalize a raw stream step tuple into a session event (core helper)."""
    from johnston.core.application.session.stream import stream_step_to_session_event as _f
    return _f(step, text_accumulator, from_stream_step=from_stream_step)


def configure_agent(
    agent: Any,
    role_key: str = "worker",
    *,
    app: Any = None,
    project_dir: Any = None,
    is_subagent: bool = False,
    worktree_branch: Any = None,
) -> Any:
    """Configure the agent role definition (core session stream helper)."""
    from johnston.core.application.session.stream import configure_agent as _f
    return _f(
        agent,
        role_key,
        app=app,
        project_dir=project_dir,
        is_subagent=is_subagent,
        worktree_branch=worktree_branch,
    )


def get_provider_actions() -> dict[str, Any]:
    """Core provider action helpers (models, credentials, thinking effort)."""
    from johnston.core.application.provider.actions import (
        fetch_grouped_models,
        get_current_thinking_effort,
        select_model,
        set_provider_credentials,
        set_thinking_effort,
    )
    return dict(
        fetch_grouped_models=fetch_grouped_models,
        get_current_thinking_effort=get_current_thinking_effort,
        select_model=select_model,
        set_provider_credentials=set_provider_credentials,
        set_thinking_effort=set_thinking_effort,
    )


def providers_to_dtos(raw: dict[str, Any]) -> list[Any]:
    """Convert the core load_providers dict shape into render-ready DTOs."""
    import os

    from johnston.core.dto import ModelInfoDTO, ProviderDTO
    from johnston.core.infrastructure.platform.paths import provider_models_cache_path
    from johnston.core.infrastructure.platform.platform_utils import cached_json_read

    dtos: list[ProviderDTO] = []
    for pkey, pdata in raw.items():
        if not isinstance(pdata, dict):
            continue
        models_raw = pdata.get("models") or []
        cache_path = str(provider_models_cache_path(str(pkey)))
        if os.path.exists(cache_path):
            try:
                cdata = cached_json_read(cache_path, {})
                if isinstance(cdata, dict):
                    c_models = cdata.get("models", [])
                    if isinstance(c_models, list) and c_models:
                        models_raw = c_models
            except Exception:
                pass

        models = [
            ModelInfoDTO(
                name=str(m),
                display_name=str(m),
                provider=str(pkey),
            )
            for m in models_raw
        ]
        enabled = bool(pdata.get("enabled", True))
        dtos.append(
            ProviderDTO(
                name=str(pdata.get("name") or pkey),
                is_configured=False,
                models=models,
                key=str(pdata.get("key") or pkey),
                is_active=False,
                is_disabled=not enabled,
            )
        )
    return dtos


def get_effort_auto() -> str:
    """Sentinel value for auto thinking effort."""
    return EFFORT_AUTO


def get_providers() -> list[Any]:
    """Provider list from core client."""
    return JohnstonClient().get_providers()


def get_gen_engine() -> dict[str, Any]:
    """Core generation engine module components."""
    from johnston.core.application.generation.engine import (
        GenCanvas,
        NullStreamDriver,
        _await_pending_git_restore,
        _create_git_checkpoint_async,
        _finalize_git_turn_async,
        _handle_interruption,
        _SessionSaveDebounce,
    )
    return dict(
        GenCanvas=GenCanvas,
        NullStreamDriver=NullStreamDriver,
        _await_pending_git_restore=_await_pending_git_restore,
        _create_git_checkpoint_async=_create_git_checkpoint_async,
        _finalize_git_turn_async=_finalize_git_turn_async,
        _handle_interruption=_handle_interruption,
        _SessionSaveDebounce=_SessionSaveDebounce,
    )
