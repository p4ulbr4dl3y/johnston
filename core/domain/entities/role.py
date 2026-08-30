"""Domain entity for AgentRole."""
from core.domain.policies.role_policy import AgentRole, RoleScope, normalize_role_scope

__all__ = ["AgentRole", "RoleScope", "normalize_role_scope"]
