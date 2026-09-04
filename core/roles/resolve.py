"""Role resolution: pick the effective role definition for a role key."""

from typing import Any, Optional

from core.domain.policies.role_policy import AgentRole, RoleScope


def resolve_role(
    registry: Any,
    role_key: str,
    project_dir: Optional[str] = None,
    is_subagent: bool = True,
) -> AgentRole:
    """Resolve the effective role definition for ``role_key``.

    Applies scope fallback rules:
    - If is_subagent is True, a role scoped to MAIN falls back to worker.
    - If is_subagent is False, a role scoped to SUBAGENT falls back to worker.
    ``get_role`` loads (and caches) the registry itself, so no separate
    ``load_roles`` call is needed.
    """
    definition = registry.get_role(role_key, project_dir=project_dir)
    if definition is None:
        definition = registry.get_role("worker", project_dir=project_dir)
    scope = getattr(definition, "scope", None)
    if is_subagent and scope == RoleScope.MAIN:
        definition = registry.get_role("worker", project_dir=project_dir)
    elif not is_subagent and scope == RoleScope.SUBAGENT:
        definition = registry.get_role("worker", project_dir=project_dir)
    if definition is None:
        definition = AgentRole(key=role_key or "worker", name=(role_key or "worker").capitalize())
    return definition

