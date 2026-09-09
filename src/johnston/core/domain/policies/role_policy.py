"""Pure role policy: AgentRole model and tool-permission checks. No IO."""
import fnmatch
from enum import Enum
from typing import Any, Callable, Optional, Tuple

from johnston.core.domain.defaults.errors import ToolResult, ToolResultStatus, format_tool_error
from johnston.core.domain.defaults.tools import SUBAGENT_EXCLUDED_TOOLS
from johnston.core.domain.entities.role import AgentRole, RoleScope, normalize_role_scope

__all__ = [
    "AgentMode",
    "AgentRole",
    "RoleScope",
    "is_role_scope_compatible",
    "normalize_role_scope",
    "role_tool_error",
]


def _canonical_tool_name(name: str) -> str:
    """Canonical tool-name form (strip + lower), mirroring runtime.normalize_tool_name.

    Local copy keeps this domain module free of infrastructure imports.
    """
    return (name or "").strip().lower()


class AgentMode(str, Enum):
    """Execution context and interaction model for an agent."""

    INTERACTIVE = "interactive"
    HEADLESS = "headless"
    SUBAGENT = "subagent"

    @property
    def is_interactive(self) -> bool:
        """True if the agent has a live interactive UI host (dialogs, question modals)."""
        return self == AgentMode.INTERACTIVE

    @property
    def is_subagent(self) -> bool:
        """True if running as an isolated background subagent reporting to a parent."""
        return self == AgentMode.SUBAGENT

    @property
    def target_scope(self) -> RoleScope:
        """Target role scope for resolving roles in this mode."""
        return RoleScope.SUBAGENT if self == AgentMode.SUBAGENT else RoleScope.MAIN


def is_role_scope_compatible(scope: Any, mode: AgentMode) -> bool:
    """Check if a role scope is compatible with the given execution mode."""
    clean = normalize_role_scope(scope)
    if clean == RoleScope.BOTH:
        return True
    if mode == AgentMode.SUBAGENT:
        return clean == RoleScope.SUBAGENT
    if mode == AgentMode.HEADLESS:
        return clean in (RoleScope.MAIN, "headless")
    if mode == AgentMode.INTERACTIVE:
        return clean in (RoleScope.MAIN, "interactive")
    return False


def _matches_tool_pattern(name: str, resolved: str, pattern: str) -> bool:
    pat = (pattern or "").strip().lower()
    if not pat:
        return False
    return fnmatch.fnmatchcase(name, pat) or fnmatch.fnmatchcase(resolved, pat)


# Single source of truth for role tool-policy checks. Used by
# role_tool_error, roles/tools, and application.generation.prompt_builder so
# disallowed, allowed_tools, and subagent exclusions are honored in one place.
def _tool_policy_result(
    role_def: Any,
    tool_name: str,
    is_subagent: bool = False,
    tool_name_normalizer: Optional[Callable[[str], str]] = None,
    mode: Optional[AgentMode] = None,
) -> Tuple[bool, Optional[str]]:
    """Evaluate a tool call against a role definition.

    Returns (allowed, reason). reason is None when allowed. When the execution
    mode is non-interactive (subagent or headless), non-interactive excluded tools
    are always denied. ``tool_name_normalizer`` canonicalizes tool names; when
    None (or on error) the name is used as-is.
    """
    if not tool_name:
        return True, None
    clean = _canonical_tool_name(tool_name)

    try:
        resolved = tool_name_normalizer(clean) if tool_name_normalizer else clean
    except Exception:
        resolved = clean

    if mode is not None and not isinstance(mode, AgentMode):
        try:
            mode = AgentMode(str(mode).lower().strip())
        except ValueError:
            mode = None

    effective_mode = mode if mode is not None else (AgentMode.SUBAGENT if is_subagent else AgentMode.INTERACTIVE)
    if not effective_mode.is_interactive and (clean in SUBAGENT_EXCLUDED_TOOLS or resolved in SUBAGENT_EXCLUDED_TOOLS):
        mode_label = "subagent roles" if effective_mode == AgentMode.SUBAGENT else f"{effective_mode.value} mode"
        return False, format_tool_error(f"tool '{clean}' disabled for {mode_label}")

    name = getattr(role_def, "name", "Role")
    if getattr(role_def, "read_only", False):
        if clean in ("create", "edit") or resolved in ("create", "edit"):
            return False, format_tool_error(f"tool '{clean}' disabled in read-only {name} role")

    disallowed = [str(t).lower() for t in (getattr(role_def, "disallowed_tools", []) or [])]
    if any(_matches_tool_pattern(clean, resolved, pat) for pat in disallowed):
        return False, format_tool_error(f"tool '{clean}' disabled in {name} role")

    allowed = [str(t).lower() for t in (getattr(role_def, "allowed_tools", []) or [])]
    if allowed and not any(_matches_tool_pattern(clean, resolved, pat) for pat in allowed):
        return False, format_tool_error(f"tool '{clean}' not in allowed tools list for {name} role")

    return True, None


# Canonical predicate for "is this tool allowed for the role?". Returns None when
# allowed, or an error ToolResult describing the denial.
def role_tool_error(
    role_def: Any,
    tool_name: str,
    is_subagent: bool = False,
    tool_name_normalizer: Optional[Callable[[str], str]] = None,
    mode: Optional[AgentMode] = None,
) -> Optional[ToolResult]:
    """Return an error ToolResult if role_def denies tool_name, else None."""
    if not role_def:
        return None
    if tool_name_normalizer is None:
        tool_name_normalizer = getattr(role_def, "tool_name_normalizer", None)
    _, reason = _tool_policy_result(
        role_def,
        tool_name,
        is_subagent=is_subagent,
        tool_name_normalizer=tool_name_normalizer,
        mode=mode,
    )
    if reason is None:
        return None
    return ToolResult(content=reason, status=ToolResultStatus.ERROR)
