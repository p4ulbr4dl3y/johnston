"""Role resolution: pick the effective role definition for a role key."""

from typing import Any, Optional

from core.domain.policies.role_policy import RoleScope


def resolve_role(registry: Any, role_key: str, project_dir: Optional[str] = None) -> Any:
    """Resolve the effective role definition for ``role_key``.

    Applies the "main-only role falls back to worker" rule: a role scoped to the
    main agent must never be used as a subagent type, so it is replaced by the
    worker role. Returns a role definition object (duck-typed).
    """
    registry.load_roles(project_dir=project_dir)
    definition = registry.get_role(role_key)
    if getattr(definition, "scope", None) == RoleScope.MAIN:
        definition = registry.get_role("worker")
    return definition
