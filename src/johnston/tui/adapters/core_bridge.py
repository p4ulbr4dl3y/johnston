"""Single boundary between TUI and core.

All data the UI renders must cross this module.  Screens, widgets and mixins
import from here (or from DTO modules) and never reach into core facades,
infrastructure or domain directly.

Layers allowed to know core:
  - this module (plus ``tui/utils/__init__``-style pure helpers re-exported here)

Layers forbidden from importing core:
  - everything else under ``src/johnston/tui`` except ``core.dto`` (data-only)
"""
from __future__ import annotations

import asyncio
from typing import Any, Optional

# --- core access (only place in TUI allowed to pull core) ---
from johnston.core.client import JohnstonClient
from johnston.core.domain.policies.messages import is_ui_visible_user_message
from johnston.core.domain.policies.models_catalog import catalog, format_context_tokens

# DTOs (data-only, safe for the rest of TUI)
from johnston.core.dto import (
    FooterCacheDTO,
    RoleInfoDTO,
    SessionSnapshotDTO,
    StatusFooterDTO,
)
from johnston.core.infrastructure.runtime.thinking_effort import display_thinking_effort
from johnston.core.infrastructure.runtime.token_util import estimate_tokens

__all__ = [
    "FooterCacheDTO",
    "RoleInfoDTO",
    "SessionSnapshotDTO",
    "StatusFooterDTO",
    "JohnstonClient",
    "catalog",
    "display_thinking_effort",
    "estimate_tokens",
    "format_context_tokens",
    "is_ui_visible_user_message",
]


def get_mcp_manager():
    """Resolve MCP manager dynamically from core infrastructure."""
    import johnston.core.infrastructure.mcp as mcp_mod

    return mcp_mod.get_mcp_manager()


def get_settings():
    """Read app settings (core config)."""
    from johnston.core.infrastructure.config.settings import get_settings as _gs

    return _gs()


def get_permission_manager():
    """Shortcut for core PermissionManager singleton."""
    from johnston.core.application.permission.permission_manager import PermissionManager

    return PermissionManager


def list_skills(*, include_hidden: bool = False):
    """List skills via core skill manager (lazy import)."""
    from johnston.core.application.skills.manager import get_skill_manager

    return get_skill_manager().list_skills(include_hidden=include_hidden)


def load_mcp_servers():
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


def collect_task_summary(app: Any, session_id: Optional[str] = None) -> tuple[list[Any], list[Any]]:
    """Return (shell_tasks, subagent_sessions) for the current app/session."""
    from johnston.core.infrastructure.runtime.task_collection import collect_current_tasks

    tasks = collect_current_tasks(app, session_id)
    return tasks.shell_tasks, tasks.subagent_tasks


def resolve_subagent_from_toolcall(tool: str, args: dict[str, Any], app: Any = None) -> str | None:
    """Resolve a subagent session id from a tool call (used by tool widgets)."""
    from johnston.core.application.session.facade import resolve_subagent_from_toolcall as _r

    return _r(tool, args, app)


def resolve_session_by_title(identifier: str, parent_id: Optional[str] = None, app: Any = None):
    """Resolve a session by title or id."""
    from johnston.core.application.session.facade import resolve_session_by_title as _r

    return _r(identifier, parent_id=parent_id, app=app)


def get_role_display_name(role_or_key: Any, project_dir: Optional[str] = None) -> str:
    """Display name for a role key."""
    from johnston.core.client import get_role_display_name as _g

    return _g(role_or_key, project_dir=project_dir)


def extract_task_status_details(task: Any) -> tuple[str, str]:
    """Task status + badge from a core task object."""
    from johnston.core.client import extract_task_status_details as _e

    return _e(task)


def get_providers() -> list[Any]:
    """Provider list from core client."""
    return JohnstonClient().get_providers()


def get_workspace_root() -> str:
    """Current workspace root path from core."""
    from johnston.core.infrastructure.platform import paths

    return paths.workspace_root()


def configure_permission_manager(tool_name_normalizer) -> None:
    """Configure the global PermissionManager singleton."""
    from johnston.core.application.permission.permission_manager import PermissionManager

    PermissionManager.configure_instance(tool_name_normalizer=tool_name_normalizer)


def configure_role_registry(tool_name_normalizer) -> None:
    """Configure the global RoleRegistry singleton."""
    from johnston.core.application.roles.role_registry import RoleRegistry

    RoleRegistry._instance = RoleRegistry(tool_name_normalizer=tool_name_normalizer)


def build_core_services(app) -> None:
    """Create provider manager, session store, task manager, agent and client facade."""
    from johnston.core.application.provider.provider_manager import ProviderManager
    from johnston.core.infrastructure.storage.session_store import SessionStore
    from johnston.core.infrastructure.tasks.manager import TaskManager

    app.pm = ProviderManager()
    app.sm = SessionStore()
    app.task_manager = TaskManager()
    app._subagent_tools: dict[str, Any] = {}
    app._background_shell_widgets: dict[str, Any] = {}
    app._foreground_shell_tasks: dict[str, Any] = {}
    app.agent = app.pm.create_active_agent()
    app.role = getattr(app.agent, "role", "worker") if app.agent else "worker"
    if app.agent:
        app.agent.app = app
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
    app._background_tasks: set[asyncio.Task] = set()


def apply_execution_mode(app, mode) -> None:
    """Set the permission execution mode from the ``--mode`` CLI flag."""
    from johnston.core.application.permission.permission_manager import PermissionManager
    from johnston.core.domain.policies.permission_policy import ExecutionMode

    try:
        PermissionManager.get_instance().set_session_mode(ExecutionMode(mode.lower()))
    except Exception:
        pass


def apply_role_to_agent(app, role) -> None:
    """Apply CLI-selected role to the active agent."""
    from johnston.core.application.roles.apply import apply_role as apply_role_to_agent

    try:
        apply_role_to_agent(app.agent, role, is_subagent=False)
        app.role = role
    except Exception:
        pass


def cancel_running_subagents(sm) -> None:
    """Cancel running subagent sessions (used on app shutdown)."""
    from johnston.core.application.session.stream import cancel_running_subagents as _c

    try:
        _c(sm)
    except Exception:
        pass


def close_tools() -> None:
    """Close all registered tool instances (used on app shutdown)."""
    from johnston.core.tools.registry import aclose_tools

    asyncio.run(aclose_tools())


def install_asyncio_exception_handler() -> None:
    """Install the global asyncio exception handler."""
    from johnston.core.infrastructure.platform.logging_setup import install_asyncio_exception_handler as _f

    _f()


def adopt_task_exception(task) -> None:
    """Attach an exception handler to a tracked task."""
    from johnston.core.infrastructure.platform.logging_setup import adopt_task_exception as _f

    _f(task)


def load_sandbox_config() -> bool:
    """Load the sandbox default from core config."""
    from johnston.core.infrastructure.config.config_helpers import load_sandbox_config as _f

    return _f()


def get_theme_variable_defaults() -> dict[str, str]:
    """Return design-token defaults from the default theme."""
    from johnston.core.domain.defaults.themes import ZINC_DARK

    return dict(ZINC_DARK.tcss_vars)


def copy_to_os_clipboard_async(text: str):
    """Copy text to the OS clipboard (async helper from core platform utils)."""
    from johnston.core.infrastructure.platform.platform_utils import copy_to_os_clipboard_async as _f

    return _f(text)
