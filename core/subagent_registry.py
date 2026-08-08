from core.role_registry import AgentRole, RoleRegistry

SubagentRegistry = RoleRegistry
SubagentDefinition = AgentRole
DEFAULT_DEFINITIONS = RoleRegistry.get_instance().list_definitions()

__all__ = ["SubagentRegistry", "SubagentDefinition", "DEFAULT_DEFINITIONS", "AgentRole"]
