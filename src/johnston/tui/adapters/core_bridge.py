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
from johnston.core.infrastructure.runtime.lru import LruCache
from johnston.core.infrastructure.runtime.thinking_effort import display_thinking_effort
from johnston.core.infrastructure.tasks.output import (
    is_spinner_line,
    process_carriage_returns,
    process_carriage_returns_lines,
    strip_ansi,
)

__all__ = [
    "FooterCacheDTO",
    "RoleInfoDTO",
    "SessionSnapshotDTO",
    "StatusFooterDTO",
    "JohnstonClient",
    "LruCache",
    "catalog",
    "display_thinking_effort",
    "estimate_tokens",
    "format_context_tokens",
    "is_spinner_line",
    "is_ui_visible_user_message",
    "process_carriage_returns",
    "process_carriage_returns_lines",
    "strip_ansi",
    "IMAGE_EXTENSIONS",
    "TEMP_IMAGES_DIR",
    "THEMES_DIR",
    "WORKTREES_DIR",
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


def get_role_registry():
    """Core RoleRegistry class (singleton access via get_instance())."""
    from johnston.core.application.roles.role_registry import RoleRegistry

    return RoleRegistry


def list_skills(*, include_hidden: bool = False):
    """List skills via core skill manager (lazy import)."""
    from johnston.core.application.skills.manager import get_skill_manager

    return get_skill_manager().list_skills(include_hidden=include_hidden)


def get_skill_manager():
    """Core skill manager singleton accessor (lazy import)."""
    from johnston.core.application.skills.manager import get_skill_manager as _f

    return _f()


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


def aclose_tools() -> Any:
    """Core tool registry async close (live lookup)."""
    from johnston.core.tools.registry import aclose_tools as _f

    return _f()


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


def save_sandbox_config(enabled: bool) -> None:
    """Persist the sandbox default (core config helper, live lookup)."""
    import johnston.core.infrastructure.config.config_helpers as _m

    _m.save_sandbox_config(enabled)


def get_theme_variable_defaults() -> dict[str, str]:
    """Return design-token defaults from the default theme."""
    from johnston.core.domain.defaults.themes import ZINC_DARK

    return dict(ZINC_DARK.tcss_vars)


def load_theme_config():
    """Load the active theme config (core config helper)."""
    from johnston.core.infrastructure.config.config_helpers import load_theme_config as _f

    return _f()


def save_theme_config(theme_name: str) -> None:
    """Persist the active theme config (core config helper)."""
    from johnston.core.infrastructure.config.config_helpers import save_theme_config as _f

    _f(theme_name)


def copy_to_os_clipboard_async(text: str):
    """Copy text to the OS clipboard (async helper from core platform utils)."""
    from johnston.core.infrastructure.platform.platform_utils import copy_to_os_clipboard_async as _f

    return _f(text)


# ---------------------------------------------------------------------------
# Infrastructure re-exports (data / pure helpers only)
# ---------------------------------------------------------------------------

def get_config_paths():
    """Core platform path constants (CONFIG_DIR, PROMPT_HISTORY_FILE, ...)."""
    from johnston.core.infrastructure.platform import paths as _paths

    return _paths


# Frequently-used path/extension constants (resolved once, data-only).
from johnston.core.infrastructure.platform.paths import (  # noqa: E402
    IMAGE_EXTENSIONS,
    TEMP_IMAGES_DIR,
    THEMES_DIR,
    WORKTREES_DIR,
)


def normalize_tool_name(name: str) -> str:
    """Normalize tool name for display and lookup."""
    from johnston.core.infrastructure.runtime.tool_name import normalize_tool_name as _f

    return _f(name)


def mcp_tool_is_known(name: str) -> bool:
    """Whether a tool name belongs to a known MCP server."""
    from johnston.core.infrastructure.mcp import mcp_tool_is_known as _f

    return _f(name)


def read_json(path: str, default: Any = None) -> Any:
    """Read a JSON file (core platform helper)."""
    from johnston.core.infrastructure.platform.platform_utils import read_json as _f

    return _f(path, default=default)


def atomic_write_json(path: str, data: Any, indent: int = 2) -> None:
    """Atomically write a JSON file (core platform helper)."""
    from johnston.core.infrastructure.platform.platform_utils import atomic_write_json as _f

    _f(path, data, indent=indent)


def get_clipboard_image_or_file(*args: Any, **kwargs: Any):
    """Return image/file from the OS clipboard (core platform helper)."""
    from johnston.core.infrastructure.platform.platform_utils import get_clipboard_image_or_file as _f

    return _f(*args, **kwargs)


def query_terminal_palette(*args: Any, **kwargs: Any):
    """Query the terminal color palette (core platform helper)."""
    from johnston.core.infrastructure.platform.terminal_theme import query_terminal_palette as _f

    return _f(*args, **kwargs)


def compute_adaptive_palette(bg: str | None = None, fg: str | None = None):
    """Compute an adapted terminal palette (core platform helper)."""
    from johnston.core.infrastructure.platform.terminal_theme import compute_adaptive_palette as _f

    return _f(bg, fg)


def filter_to_session(tasks, session_id):
    """Filter tasks to the given session scope (core task manager helper)."""
    from johnston.core.infrastructure.tasks.manage import filter_to_session as _f

    return _f(tasks, session_id)


def format_duration(seconds: float | int | None) -> str:
    """Format a duration as a concise string (core task helper)."""
    from johnston.core.infrastructure.tasks.manage import format_duration as _f

    return _f(seconds)


def collect_current_tasks(app, session_id=None):
    """Collect shell/subagent task state for the status footer (core helper)."""
    from johnston.core.infrastructure.runtime.task_collection import collect_current_tasks as _f

    return _f(app, session_id)


def worktrees_dir():
    """Resolve the worktrees directory live from core paths (test-overridable)."""
    import johnston.core.infrastructure.platform.paths as _m

    return getattr(_m, "WORKTREES_DIR", "") or ""


def get_branch_info(cwd=None):
    """Detect the current git branch (core git metrics helper)."""
    from johnston.core.infrastructure.platform.git_metrics import get_branch_info as _f

    return _f(cwd)


def get_diff_stats(cwd=None):
    """Compute '+add/-del' diff stats vs HEAD (core git metrics helper)."""
    from johnston.core.infrastructure.platform.git_metrics import get_diff_stats as _f

    return _f(cwd)


def make_git_diff(old_content, new_content, *, fromfile="file", tofile="file", context=3):
    """Generate a unified diff for two content strings (core git helper)."""
    from johnston.core.infrastructure.runtime.git_utils import make_git_diff as _f

    return _f(old_content, new_content, fromfile=fromfile, tofile=tofile, context=context)


def list_branches_and_worktrees(project_dir):
    """List git branches and worktrees (core git worktree helper)."""
    from johnston.core.infrastructure.runtime.git_worktree import GitWorktreeManager as _f

    return _f.list_branches_and_worktrees(project_dir)


def get_git_worktree_manager():
    """Core GitWorktreeManager class (lazy, for feature/async detection)."""
    from johnston.core.infrastructure.runtime.git_worktree import GitWorktreeManager as _f

    return _f


def build_prompt_builder(
    base_system_prompt,
    base_tools,
    *,
    role="worker",
    is_subagent=False,
    subagent_schema=None,
):
    """Instantiate the core PromptBuilder bound to an agent's prompt/tools."""
    import johnston.core.application.generation.prompt_builder as _m

    return _m.PromptBuilder(
        base_system_prompt,
        base_tools,
        role=role,
        is_subagent=is_subagent,
        subagent_schema=subagent_schema,
    )


def advance_generation_engine(provider_manager, agent):
    """(async) Ensure the active provider is ready for generation (core engine)."""
    from johnston.core.application.generation.engine import ensure_provider_ready as _f

    return _f(provider_manager, agent)


def get_provider_ready_state():
    """Provider readiness enum from the core generation engine."""
    from johnston.core.application.generation.engine import ProviderReadyState as _f

    return _f


def get_gen_engine():
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


def sync_session_metrics(session, agent):
    """Sync context/token metrics onto the session (core stream helper)."""
    from johnston.core.application.session.stream import sync_session_metrics as _f

    return _f(session, agent)


def stream_step_to_session_event(step, text_accumulator=None, *, from_stream_step=False):
    """Canonicalize a raw stream step tuple into a session event (core helper)."""
    from johnston.core.application.session.stream import stream_step_to_session_event as _f

    return _f(step, text_accumulator, from_stream_step=from_stream_step)


def configure_agent(
    agent,
    role_key="worker",
    *,
    app=None,
    project_dir=None,
    is_subagent=False,
    worktree_branch=None,
):
    """Configure the agent's role definition (core session stream helper)."""
    from johnston.core.application.session.stream import configure_agent as _f

    return _f(
        agent,
        role_key,
        app=app,
        project_dir=project_dir,
        is_subagent=is_subagent,
        worktree_branch=worktree_branch,
    )


def execute_shell_command(command, *, host=None, session=None, agent=None):
    """(async) Run a shell command through the core session executor."""
    from johnston.core.application.session.shell_executor import execute_shell_command as _f

    return _f(command, host=host, session=session, agent=agent)


def auto_title_session(agent, session):
    """(async) Auto-generate a session title (core session helper)."""
    from johnston.core.application.session.auto_title import auto_title_session as _f

    return _f(agent, session)


def get_session_actions():
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


def clean_heuristic_title(text: str, max_len: int = 60) -> str:
    """Clean a heuristic session title (core auto_title helper)."""
    from johnston.core.application.session.auto_title import clean_heuristic_title as _f

    return _f(text, max_len=max_len)


def cycle_execution_mode():
    """Cycle permission execution mode: review -> edits -> yolo -> review."""
    from johnston.core.application.permission.interactor import cycle_execution_mode as _f

    return _f()


def apply_permission_choice(choice, permission_name):
    """Apply a permission choice onto the permission manager singleton."""
    from johnston.core.application.permission.interactor import apply_permission_choice as _f

    return _f(choice, permission_name)


def get_provider_actions():
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


def get_skill_helpers():
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


def estimate_tokens(text: Any) -> int:
    """Estimate token count for text (core runtime helper, live lookup)."""
    import johnston.core.infrastructure.runtime.token_util as _m

    return _m.estimate_tokens(text)


def get_effort_auto() -> str:
    """Sentinel value for 'auto' thinking effort."""
    from johnston.core.client import EFFORT_AUTO as _f

    return _f


def is_windows() -> bool:
    """True on Windows platform (core platform helper)."""
    from johnston.core.client import is_windows as _f

    return _f()


def get_mcp_service(*args: Any, **kwargs: Any):
    """Instantiate core McpService."""
    from johnston.core.client import McpService as _f

    return _f(*args, **kwargs)


def kill_subagent(session, app=None) -> bool:
    """Kill a subagent session (core client facade)."""
    from johnston.core.client import kill_subagent as _f

    return _f(session, app)


def get_store(app=None):
    """Resolve the session store (core client facade, live lookup)."""
    from johnston.core.client import _get_store as _f

    return _f(app)


def get_extract_task_status_details():
    """Core task status extraction helper."""
    from johnston.core.client import extract_task_status_details as _f

    return _f


def get_theme_constants():
    """Theme/status color constants from core domain defaults."""
    from johnston.core.domain.defaults.config import (
        COLOR_DIFF_ADD_BG,
        COLOR_DIFF_ADD_FG,
        COLOR_DIFF_GUTTER,
        COLOR_DIFF_REMOVE_BG,
        COLOR_DIFF_REMOVE_FG,
        COLOR_STATUS_ERROR,
        COLOR_STATUS_RUNNING,
        COLOR_STATUS_SUCCESS,
        THEME_MUTED,
        THEME_PRIMARY,
        THEME_SECONDARY,
        THEME_SUBTLE,
    )

    return dict(
        COLOR_DIFF_ADD_BG=COLOR_DIFF_ADD_BG,
        COLOR_DIFF_ADD_FG=COLOR_DIFF_ADD_FG,
        COLOR_DIFF_GUTTER=COLOR_DIFF_GUTTER,
        COLOR_DIFF_REMOVE_BG=COLOR_DIFF_REMOVE_BG,
        COLOR_DIFF_REMOVE_FG=COLOR_DIFF_REMOVE_FG,
        COLOR_STATUS_ERROR=COLOR_STATUS_ERROR,
        COLOR_STATUS_RUNNING=COLOR_STATUS_RUNNING,
        COLOR_STATUS_SUCCESS=COLOR_STATUS_SUCCESS,
        THEME_MUTED=THEME_MUTED,
        THEME_PRIMARY=THEME_PRIMARY,
        THEME_SECONDARY=THEME_SECONDARY,
        THEME_SUBTLE=THEME_SUBTLE,
    )


def get_fork_base_max_len() -> int:
    """Max length for fork titles (core session naming policy)."""
    from johnston.core.domain.policies.session_naming import FORK_BASE_MAX_LEN as _f

    return _f


def get_theme_vars():
    """Design tokens used by the markdown/theme layer (core defaults)."""
    from johnston.core.domain.defaults.themes import ZINC_DARK as _f

    return _f


def list_themes():
    """List available themes (core defaults, live lookup)."""
    import johnston.core.domain.defaults.themes as _m

    return _m.list_themes()


def get_theme_by_name(name: str):
    """Resolve a theme by name (core defaults, live lookup)."""
    import johnston.core.domain.defaults.themes as _m

    return _m.get_theme(name)


def is_ansi_theme(theme) -> bool:
    """Whether a theme is ANSI-based (core entity helper)."""
    from johnston.core.domain.entities.theme import is_ansi_theme as _f

    return _f(theme)


def get_theme_class():
    """Core Theme entity class."""
    from johnston.core.domain.entities.theme import Theme as _f

    return _f


def get_ignore_dirs() -> list[str]:
    """Default git-ignore directory names (core defaults)."""
    from johnston.core.domain.defaults.git_excludes import DEFAULT_IGNORE_DIRS as _f

    return _f


def truncate_output(*args, **kwargs):
    """Truncate tool output for display (core tools base, live lookup)."""
    from johnston.core.tools.base import truncate_output as _f

    return _f(*args, **kwargs)


def format_background_notification(*args, **kwargs):
    """Format a background-task completion notification (core tools base)."""
    from johnston.core.tools.base import format_background_notification as _f

    return _f(*args, **kwargs)


def is_builtin_tool(name: str) -> bool:
    """Whether a tool name is registered in the core tool registry."""
    from johnston.core.tools.registry import REGISTRY as _r

    return name in _r


def get_user_event_type() -> str:
    """Transcript event type for user messages (core messages policy)."""
    from johnston.core.domain.policies.messages import USER_EVENT_TYPE as _f

    return _f


def transcript_before_turn(messages, up_to_idx):
    """Slice transcript events up to (not including) a user turn (core policy)."""
    from johnston.core.domain.policies.messages import transcript_before_turn as _f

    return _f(messages, up_to_idx)
