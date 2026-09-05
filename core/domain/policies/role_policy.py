"""Pure role policy: AgentRole model and tool-permission checks. No IO."""
import fnmatch
from enum import Enum
from typing import Any, Callable, List, Optional, Tuple

from core.domain.defaults.errors import ToolResult, ToolResultStatus, format_tool_error
from core.domain.defaults.tools import SUBAGENT_EXCLUDED_TOOLS
from core.domain.policies.provider import split_provider_model


def _canonical_tool_name(name: str) -> str:
    """Canonical tool-name form (strip + lower), mirroring runtime.normalize_tool_name.

    Local copy keeps this domain module free of infrastructure imports.
    """
    return (name or "").strip().lower()


class RoleScope(str, Enum):
    """The agent contexts a role applies to."""

    BOTH = "any"
    MAIN = "main"
    SUBAGENT = "subagent"


def normalize_role_scope(scope: str) -> str:
    """Normalize a role scope value to its canonical short name."""
    clean = (scope or "").strip().lower()
    if clean in ("both", "all"):
        return "any"
    return clean or "any"


class AgentRole:
    """Unified definition for agent execution roles and modes."""

    def __init__(
        self,
        key: str,
        name: str = "",
        description: str = "",
        prompt: str = "",
        disallowed_tools: Optional[List[str]] = None,
        allowed_tools: Optional[List[str]] = None,
        model: str = "",
        provider: str = "",
        scope: str = "any",
        source: str = "builtin",
        tool_name_normalizer: Optional[Callable[[str], str]] = None,
        read_only: bool = False,
    ):
        self.key = key.lower().strip()
        self.name = name or self.key.capitalize()
        self.description = description
        self.prompt = prompt or ""
        self.disallowed_tools = [t.strip() for t in (disallowed_tools or [])]
        self.allowed_tools = [t.strip() for t in (allowed_tools or [])]
        raw_model = (model or "").strip()
        raw_provider = (provider or "").strip().lower()
        if not raw_provider and "/" in raw_model:
            self.provider, self.model = split_provider_model(raw_model)
        else:
            self.provider = raw_provider
            self.model = raw_model
        self.scope = normalize_role_scope(scope)
        self.source = source
        self.tool_name_normalizer = tool_name_normalizer
        self.read_only = bool(read_only)


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
) -> Tuple[bool, Optional[str]]:
    """Evaluate a tool call against a role definition.

    Returns (allowed, reason). reason is None when allowed. When ``is_subagent``
    is set, subagent-excluded tools are always denied. ``tool_name_normalizer``
    canonicalizes tool names; when None (or on error) the name is used as-is.
    """
    if not tool_name:
        return True, None
    clean = _canonical_tool_name(tool_name)

    try:
        resolved = tool_name_normalizer(clean) if tool_name_normalizer else clean
    except Exception:
        resolved = clean

    if is_subagent and (clean in SUBAGENT_EXCLUDED_TOOLS or resolved in SUBAGENT_EXCLUDED_TOOLS):
        return False, format_tool_error(f"tool '{clean}' disabled for subagent roles")

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
) -> Optional[ToolResult]:
    """Return an error ToolResult if role_def denies tool_name, else None."""
    if not role_def:
        return None
    if tool_name_normalizer is None:
        tool_name_normalizer = getattr(role_def, "tool_name_normalizer", None)
    _, reason = _tool_policy_result(
        role_def, tool_name, is_subagent=is_subagent, tool_name_normalizer=tool_name_normalizer
    )
    if reason is None:
        return None
    return ToolResult(content=reason, status=ToolResultStatus.ERROR)
