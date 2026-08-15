"""Pure role policy: AgentRole model and tool-permission checks. No IO."""
from typing import Any, Callable, List, Optional, Tuple

from core.domain.defaults.tools import SUBAGENT_EXCLUDED_TOOLS, WRITE_TOOLS
from core.infrastructure.errors import format_tool_error

# Legacy scope aliases -> canonical names. Kept indefinitely so existing role
# files (and persisted sessions) keep working after the rename.
_SCOPE_ALIASES = {
    "main_only": "main",
    "subagent_only": "subagent",
}


def normalize_role_scope(scope: str) -> str:
    """Normalize a role scope value to its canonical short name."""
    clean = (scope or "").strip().lower() or "any"
    return _SCOPE_ALIASES.get(clean, clean)


class AgentRole:
    """Unified definition for agent execution roles and modes."""

    def __init__(
        self,
        key: str,
        name: str = "",
        description: str = "",
        prompt: str = "",
        read_only: bool = False,
        disallowed_tools: Optional[List[str]] = None,
        allowed_tools: Optional[List[str]] = None,
        model: str = "",
        provider: str = "",
        scope: str = "any",
        source: str = "builtin",
        tool_name_normalizer: Optional[Callable[[str], str]] = None,
    ):
        self.key = key.lower().strip()
        self.name = name or self.key.capitalize()
        self.description = description
        self.prompt = prompt or ""
        self.read_only = read_only
        self.disallowed_tools = [t.strip() for t in (disallowed_tools or [])]
        self.allowed_tools = [t.strip() for t in (allowed_tools or [])]
        self.model = model
        self.provider = (provider or "").strip().lower()
        self.scope = normalize_role_scope(scope)
        self.source = source
        self.tool_name_normalizer = tool_name_normalizer

    @property
    def system_prompt(self) -> str:
        return self.prompt

    def is_tool_allowed(self, tool_name: str) -> Optional[str]:
        """Returns an error string if this role disables tool_name, else None."""
        return role_tool_error(self, tool_name, tool_name_normalizer=getattr(self, "tool_name_normalizer", None))


# Single source of truth for role/mode tool-policy checks. Used by
# role_tool_error, AgentRole.is_tool_allowed, roles/tools, and application.generation.prompt_builder so
# disallowed, read_only, allowed_tools, and subagent exclusions are honored in
# one place.
def _tool_policy_result(
    role_def: Any,
    tool_name: str,
    is_subagent: bool = False,
    tool_name_normalizer: Optional[Callable[[str], str]] = None,
) -> Tuple[bool, Optional[str]]:
    """Evaluate a tool call against a role or mode object.

    Returns (allowed, reason). reason is None when allowed. Works with both
    AgentRole instances and duck-typed mode objects exposing disallowed_tools,
    read_only, allowed_tools, and name attributes. When ``is_subagent`` is set,
    subagent-excluded tools are always denied. ``tool_name_normalizer`` canonicalizes
    tool names; when None (or on error) the name is used as-is.
    """
    if not tool_name:
        return True, None
    clean = (tool_name or "").strip().lower()
    if clean.startswith("functions."):
        clean = clean.split(".", 1)[1]

    try:
        resolved = tool_name_normalizer(clean) if tool_name_normalizer else clean
    except Exception:
        resolved = clean

    if is_subagent and (clean in SUBAGENT_EXCLUDED_TOOLS or resolved in SUBAGENT_EXCLUDED_TOOLS):
        return False, format_tool_error(f"tool '{clean}' disabled for subagent roles")

    name = getattr(role_def, "name", "Role")
    disallowed = [t.lower() for t in (getattr(role_def, "disallowed_tools", []) or [])]
    if clean in disallowed or resolved in disallowed:
        return False, format_tool_error(f"tool '{clean}' disabled in {name} role")

    if getattr(role_def, "read_only", False) and (clean in WRITE_TOOLS or resolved in WRITE_TOOLS):
        return False, format_tool_error(f"tool '{clean}' disabled in read-only {name} role")

    allowed = [t.lower() for t in (getattr(role_def, "allowed_tools", []) or [])]
    if allowed and clean not in allowed and resolved not in allowed:
        return False, format_tool_error(f"tool '{clean}' not in allowed tools list for {name} role")

    return True, None


# Canonical predicate for "is this tool allowed for the role?". Returns None when
# allowed, or an error string describing the denial.
def role_tool_error(
    role_def: Any,
    tool_name: str,
    is_subagent: bool = False,
    tool_name_normalizer: Optional[Callable[[str], str]] = None,
) -> Optional[str]:
    """Return an error string if role_def denies tool_name, else None."""
    if not role_def:
        return None
    if tool_name_normalizer is None:
        tool_name_normalizer = getattr(role_def, "tool_name_normalizer", None)
    _, reason = _tool_policy_result(
        role_def, tool_name, is_subagent=is_subagent, tool_name_normalizer=tool_name_normalizer
    )
    return reason
