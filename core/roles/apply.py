"""Facade: orchestrate role resolution, provider, tools, and prompt in order."""

from typing import Any, Optional

from core.domain.policies.role_policy import AgentRole
from core.roles.prompt import apply_prompt
from core.roles.provider import apply_provider
from core.roles.resolve import resolve_role
from core.roles.tools import apply_role_tools


def apply_role(
    agent: Any,
    role_key: str,
    project_dir: Optional[str] = None,
    worktree_branch: Optional[str] = None,
    is_subagent: Optional[bool] = None,
) -> AgentRole:
    """Apply a role definition to an agent (main or subagent).

    Resolves the effective role (with scope fallback), switches provider
    if pinned, filters/hardens tools, and sets the system prompt and model.
    Returns the resolved role definition.
    """
    from core.role_registry import RoleRegistry

    if is_subagent is None:
        is_subagent = getattr(agent, "is_subagent", False)

    registry = RoleRegistry.get_instance()
    definition = resolve_role(registry, role_key, project_dir=project_dir, is_subagent=is_subagent)
    try:
        if is_subagent:
            agent.role = definition.key
        else:
            agent.role = role_key or definition.key
        agent.role_name = definition.name
        agent.read_only = getattr(definition, "read_only", False)
    except Exception:
        pass

    apply_provider(agent, definition)
    apply_role_tools(agent, definition, is_subagent=is_subagent)
    apply_prompt(agent, definition, worktree_branch=worktree_branch, is_subagent=is_subagent)
    return definition


