"""Facade: orchestrate role resolution, provider, tools, and prompt in order."""

from typing import Any, Optional

from core.domain.policies.role_policy import AgentMode, AgentRole
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
    mode: Optional[AgentMode] = None,
) -> AgentRole:
    """Apply a role definition to an agent (interactive, headless, or subagent).

    Resolves the effective role (with mode scope fallback), switches provider
    if pinned, filters/hardens tools, and sets the system prompt and model.
    Returns the resolved role definition.
    """
    from core.role_registry import RoleRegistry

    if mode is not None:
        effective_mode = AgentMode(mode.lower().strip()) if isinstance(mode, str) else mode
    elif is_subagent is not None:
        effective_mode = AgentMode.SUBAGENT if is_subagent else AgentMode.INTERACTIVE
    else:
        agent_mode = getattr(agent, "mode", None)
        if isinstance(agent_mode, AgentMode):
            effective_mode = agent_mode
        elif isinstance(agent_mode, str):
            try:
                effective_mode = AgentMode(agent_mode.lower().strip())
            except ValueError:
                effective_mode = AgentMode.SUBAGENT if getattr(agent, "is_subagent", False) else AgentMode.INTERACTIVE
        else:
            effective_mode = AgentMode.SUBAGENT if getattr(agent, "is_subagent", False) else AgentMode.INTERACTIVE

    mode = effective_mode

    agent.mode = mode
    agent.is_subagent = mode.is_subagent
    agent.is_headless = (mode == AgentMode.HEADLESS)

    registry = RoleRegistry.get_instance()
    definition = resolve_role(registry, role_key, project_dir=project_dir, mode=mode)
    try:
        if mode == AgentMode.SUBAGENT:
            agent.role = definition.key
        else:
            agent.role = role_key or definition.key
        agent.role_name = definition.name
        agent.read_only = getattr(definition, "read_only", False)
    except Exception:
        pass

    apply_provider(agent, definition)
    apply_role_tools(agent, definition, mode=mode)
    apply_prompt(agent, definition, worktree_branch=worktree_branch, mode=mode)
    return definition


