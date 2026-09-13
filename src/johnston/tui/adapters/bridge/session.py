"""Session, permission, and skill bridge adapters between TUI and core."""
from __future__ import annotations

from typing import Any, Optional

from johnston.core.domain.policies.messages import is_ui_visible_user_message

__all__ = [
    "apply_execution_mode",
    "apply_permission_choice",
    "auto_title_session",
    "cancel_running_subagents",
    "clean_heuristic_title",
    "configure_permission_manager",
    "cycle_execution_mode",
    "execute_shell_command",
    "get_fork_base_max_len",
    "get_permission_manager",
    "get_session_actions",
    "get_skill_helpers",
    "get_skill_manager",
    "get_store",
    "get_user_event_type",
    "is_ui_visible_user_message",
    "list_skills",
    "resolve_session_by_title",
    "resolve_subagent_from_toolcall",
    "transcript_before_turn",
]


def resolve_subagent_from_toolcall(
    tool: str, args: dict[str, Any], app: Any = None
) -> str | None:
    """Resolve a subagent session id from a tool call (used by tool widgets)."""
    from johnston.core.application.session.facade import (
        resolve_subagent_from_toolcall as _r,
    )

    return _r(tool, args, app)


def resolve_session_by_title(
    identifier: str, parent_id: Optional[str] = None, app: Any = None
) -> Any:
    """Resolve a session by title or id."""
    from johnston.core.application.session.facade import (
        resolve_session_by_title as _r,
    )

    return _r(identifier, parent_id=parent_id, app=app)


def cancel_running_subagents(sm: Any, parent_id: str | None = None) -> int:
    """Cancel running subagent sessions (used on app shutdown / rewind)."""
    from johnston.core.application.session.stream import (
        cancel_running_subagents as _c,
    )

    try:
        return _c(sm, parent_id)
    except Exception:
        pass
    return 0


def auto_title_session(agent: Any, session: Any) -> Any:
    """(async) Auto-generate a session title (core session helper)."""
    from johnston.core.application.session.auto_title import (
        auto_title_session as _f,
    )

    return _f(agent, session)


def clean_heuristic_title(text: str, max_len: int = 60) -> str:
    """Clean a heuristic session title (core auto_title helper)."""
    from johnston.core.application.session.auto_title import (
        clean_heuristic_title as _f,
    )

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
    from johnston.core.domain.policies.session_naming import (
        FORK_BASE_MAX_LEN as _f,
    )

    return _f


def get_permission_manager() -> Any:
    """Shortcut for core PermissionManager singleton."""
    from johnston.core.application.permission.permission_manager import (
        PermissionManager,
    )

    return PermissionManager


def configure_permission_manager(tool_name_normalizer: Any) -> None:
    """Configure the global PermissionManager singleton."""
    from johnston.core.application.permission.permission_manager import (
        PermissionManager,
    )

    PermissionManager.configure_instance(tool_name_normalizer=tool_name_normalizer)


def apply_execution_mode(app: Any, mode: str) -> None:
    """Set the permission execution mode from the ``--mode`` CLI flag."""
    from johnston.core.application.permission.permission_manager import (
        PermissionManager,
    )
    from johnston.core.domain.policies.permission_policy import ExecutionMode

    try:
        PermissionManager.get_instance().set_session_mode(ExecutionMode(mode.lower()))
    except Exception:
        pass


def cycle_execution_mode() -> Any:
    """Cycle permission execution mode: review -> edits -> yolo -> review."""
    from johnston.core.application.permission.interactor import (
        cycle_execution_mode as _f,
    )

    return _f()


def apply_permission_choice(choice: Any, permission_name: Any) -> Any:
    """Apply a permission choice onto the permission manager singleton."""
    from johnston.core.application.permission.interactor import (
        apply_permission_choice as _f,
    )

    return _f(choice, permission_name)


def list_skills(*, include_hidden: bool = False) -> Any:
    """List skills via core skill manager (lazy import)."""
    from johnston.core.application.skills.manager import get_skill_manager

    return get_skill_manager().list_skills(include_hidden=include_hidden)


def get_skill_manager() -> Any:
    """Core skill manager singleton accessor (lazy import)."""
    from johnston.core.application.skills.manager import (
        get_skill_manager as _f,
    )

    return _f()


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


def execute_shell_command(
    command: str,
    *,
    host: Any = None,
    session: Any = None,
    agent: Any = None,
) -> Any:
    """(async) Run a shell command through the core session executor."""
    from johnston.core.application.session.shell_executor import (
        execute_shell_command as _f,
    )

    return _f(command, host=host, session=session, agent=agent)


def get_store(app: Any = None) -> Any:
    """Resolve the session store (core client facade, live lookup)."""
    from johnston.core.client import _get_store as _f

    return _f(app)


def get_user_event_type() -> str:
    """Transcript event type for user messages (core messages policy)."""
    from johnston.core.domain.policies.messages import USER_EVENT_TYPE as _f

    return _f


def transcript_before_turn(messages: list[Any], up_to_idx: int) -> list[Any]:
    """Slice transcript events up to (not including) a user turn (core policy)."""
    from johnston.core.domain.policies.messages import transcript_before_turn as _f

    return _f(messages, up_to_idx)
