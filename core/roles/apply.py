"""Facade: orchestrate role resolution, provider, tools, and prompt in order."""

from typing import Any, Optional

from core.domain.policies.role_policy import AgentRole
from core.roles.prompt import apply_prompt
from core.roles.provider import apply_provider
from core.roles.resolve import resolve_role
from core.roles.tools import apply_role_tools


def apply_role(subagent: Any, role_key: str, project_dir: Optional[str] = None) -> AgentRole:
    """Apply a role definition to a subagent agent.

    Resolves the effective role (with main->worker fallback), switches provider
    if pinned, filters/hardens tools, and sets the system prompt and model.
    Returns the resolved role definition.
    """
    from core.role_registry import RoleRegistry

    registry = RoleRegistry.get_instance()
    definition = resolve_role(registry, role_key, project_dir=project_dir)
    apply_provider(subagent, definition)
    apply_role_tools(subagent, definition)
    apply_prompt(subagent, definition)
    return definition
