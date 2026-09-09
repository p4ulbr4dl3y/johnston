"""Role resolution: pick the effective role definition for a role key."""

from typing import Any, Optional

from johnston.core.domain.policies.role_policy import (
    AgentMode,
    AgentRole,
    is_role_scope_compatible,
)


def resolve_role(
    registry: Any,
    role_key: str,
    project_dir: Optional[str] = None,
    is_subagent: bool = True,
    mode: Optional[AgentMode] = None,
) -> AgentRole:
    """Resolve the effective role definition for ``role_key``.

    Applies scope fallback rules:
    - Checks whether role scope is compatible with execution mode via ``is_role_scope_compatible``.
    - Falls back to ``worker`` role if incompatible.
    ``get_role`` loads (and caches) the registry itself, so no separate
    ``load_roles`` call is needed.
    """
    effective_mode = mode if mode is not None else (AgentMode.SUBAGENT if is_subagent else AgentMode.INTERACTIVE)
    definition = registry.get_role(role_key, project_dir=project_dir)
    if definition is None:
        definition = registry.get_role("worker", project_dir=project_dir)
    scope = getattr(definition, "scope", None)
    if scope and not is_role_scope_compatible(str(scope), effective_mode):
        definition = registry.get_role("worker", project_dir=project_dir)
    if definition is None:
        definition = AgentRole(key=role_key or "worker", name=(role_key or "worker").capitalize())
    return definition

