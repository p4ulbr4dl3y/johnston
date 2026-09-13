"""Client, provider, role, model, and generation bridge adapters."""
from __future__ import annotations

from typing import Any, Optional

from johnston.core.application.generation.engine import ProviderReadyState
from johnston.core.client import JohnstonClient
from johnston.core.domain.policies.models_catalog import catalog, format_context_tokens
from johnston.core.dto import (
    FooterCacheDTO,
    ModelInfoDTO,
    ProviderDTO,
    RoleInfoDTO,
    SessionSnapshotDTO,
    StatusFooterDTO,
)
from johnston.core.infrastructure.runtime.thinking_effort import display_thinking_effort

__all__ = [
    "FooterCacheDTO",
    "JohnstonClient",
    "ModelInfoDTO",
    "ProviderDTO",
    "ProviderReadyState",
    "RoleInfoDTO",
    "SessionSnapshotDTO",
    "StatusFooterDTO",
    "active_mcp_server_count",
    "advance_generation_engine",
    "apply_role_to_agent",
    "build_core_services",
    "build_prompt_builder",
    "catalog",
    "configure_agent",
    "configure_role_registry",
    "display_thinking_effort",
    "ensure_provider_ready",
    "estimate_tokens",
    "format_context_tokens",
    "get_effort_auto",
    "get_gen_engine",
    "get_mcp_manager",
    "get_mcp_service",
    "get_provider_actions",
    "get_provider_ready_state",
    "get_providers",
    "get_role_display_name",
    "get_role_registry",
    "load_mcp_servers",
    "mcp_tool_is_known",
    "providers_to_dtos",
    "stream_step_to_session_event",
    "sync_session_metrics",
]


def get_mcp_manager() -> Any:
    """Resolve MCP manager dynamically from core infrastructure."""
    import johnston.core.infrastructure.mcp as mcp_mod

    return mcp_mod.get_mcp_manager()


def load_mcp_servers() -> Any:
    """Load MCP servers via core MCP manager."""
    return get_mcp_manager().load_servers()


def active_mcp_server_count(servers: list[Any]) -> int:
    """Number of currently-active MCP servers among ``servers``."""
    try:
        fn = getattr(get_mcp_manager(), "active_server_count", None)
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


def get_role_display_name(role_or_key: Any, project_dir: Optional[str] = None) -> str:
    """Display name for a role key."""
    from johnston.core.client import get_role_display_name as _g

    return _g(role_or_key, project_dir=project_dir)


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


def get_providers() -> list[Any]:
    """Provider list from core client."""
    return JohnstonClient().get_providers()


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
        # Fresh TUI agents are interactive; the client default is HEADLESS.
        app.agent.mode = AgentMode.INTERACTIVE
        app.agent.is_headless = False
        app.agent.is_subagent = False
    app.client = JohnstonClient(
        pm=app.pm,
        store=app.sm,
        agent=app.agent,
        task_manager=app.task_manager,
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
    """Instantiate the core PromptBuilder bound to an agent's prompt/tools."""
    import johnston.core.application.generation.prompt_builder as _m

    return _m.PromptBuilder(
        base_system_prompt,
        base_tools,
        role=role,
        is_subagent=is_subagent,
        subagent_schema=subagent_schema,
    )


def ensure_provider_ready(provider_manager: Any, agent: Any) -> Any:
    """Ensure the active provider is ready for generation (core engine)."""
    from johnston.core.application.generation.engine import ensure_provider_ready as _f

    return _f(provider_manager, agent)


def advance_generation_engine(provider_manager: Any, agent: Any) -> Any:
    """(async) Ensure the active provider is ready for generation (core engine)."""
    return ensure_provider_ready(provider_manager, agent)


def get_provider_ready_state() -> type[ProviderReadyState]:
    """Provider readiness enum from the core generation engine."""
    from johnston.core.application.generation.engine import ProviderReadyState as _f

    return _f


def get_gen_engine() -> dict[str, Any]:
    """Core generation engine module (GenCanvas, stream drivers, git wraps)."""
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


def sync_session_metrics(session: Any, agent: Any) -> Any:
    """Sync context/token metrics onto the session (core stream helper)."""
    from johnston.core.application.session.stream import (
        sync_session_metrics as _f,
    )

    return _f(session, agent)


def stream_step_to_session_event(
    step: Any, text_accumulator: Any = None, *, from_stream_step: bool = False
) -> Any:
    """Canonicalize a raw stream step tuple into a session event (core helper)."""
    from johnston.core.application.session.stream import (
        stream_step_to_session_event as _f,
    )

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
    """Configure the agent's role definition (core session stream helper)."""
    from johnston.core.application.session.stream import (
        configure_agent as _f,
    )

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


def providers_to_dtos(raw: dict[str, Any]) -> list[ProviderDTO]:
    """Convert the core ``load_providers`` dict shape into render-ready DTOs."""
    dtos: list[ProviderDTO] = []
    for pkey, pdata in raw.items():
        if not isinstance(pdata, dict):
            continue
        models_raw = pdata.get("models") or []
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


def estimate_tokens(text: Any) -> int:
    """Estimate token count for text (core runtime helper, live lookup)."""
    import johnston.core.infrastructure.runtime.token_util as _m

    return _m.estimate_tokens(text)


def get_effort_auto() -> str:
    """Sentinel value for 'auto' thinking effort."""
    from johnston.core.client import EFFORT_AUTO as _f

    return _f
