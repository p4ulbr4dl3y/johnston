"""Role resolution: pick the effective role definition for a role key."""

from typing import Any, Optional

from core.domain.policies.role_policy import AgentRole, RoleScope


def resolve_role(registry: Any, role_key: str, project_dir: Optional[str] = None) -> AgentRole:
    """Resolve the effective role definition for ``role_key``.

    Applies the "main-only role falls back to worker" rule: a role scoped to the
    main agent must never be used as a subagent type, so it is replaced by the
    worker role. ``get_role`` loads (and caches) the registry itself, so no
    separate ``load_roles`` call is needed.
    """
    definition = registry.get_role(role_key, project_dir=project_dir)
    if getattr(definition, "scope", None) == RoleScope.MAIN:
        definition = registry.get_role("worker")
    return definition
