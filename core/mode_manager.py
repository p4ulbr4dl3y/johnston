from core.config import CONFIG_DIR
from core.role_registry import AgentRole, RoleRegistry, role_tool_error

ModeManager = RoleRegistry
ModeDefinition = AgentRole
mode_tool_error = role_tool_error
BUILTIN_MODES = RoleRegistry.get_instance().roles

__all__ = ["ModeManager", "ModeDefinition", "mode_tool_error", "BUILTIN_MODES", "AgentRole", "CONFIG_DIR"]
