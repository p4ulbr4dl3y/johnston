"""Pure permission policy helpers (no state, no IO)."""

from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict


class PermissionAction(str, Enum):
    """Outcome of a tool permission check."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


VALID_ACTIONS = frozenset(action.value for action in PermissionAction)


@dataclass(frozen=True)
class PermissionDecision:
    """Result of a tool permission check: the action and a human-readable reason."""

    action: PermissionAction
    reason: str


# Builtin tools that are NOT covered by an explicit config entry fall back to
# the configured default action (ask/deny). MCP tools (not in this set) default
# to 'allow'. Used as the fallback when no builtin_tool_names frozenset is
# injected via DI.
_BUILTIN_TOOLS = frozenset(
    {
        "read",
        "create",
        "edit",
        "multi_edit",
        "shell",
        "ask_user",
        "web_fetch",
        "invoke_subagent",
        "manage_subagent",
        "manage_shell",
        "update_plan",
    }
)


def normalize_action(action: str, default: str = "ask") -> str:
    """Normalizes an action to 'allow'/'ask'/'deny'. Invalid values fall back to default."""
    if isinstance(action, str):
        cleaned = action.strip().lower()
        if cleaned in VALID_ACTIONS:
            return cleaned
    return default


def _merge_perms(base: Dict[str, Any], override: Dict[str, Any]) -> None:
    if not override:
        return
    if "default" in override and isinstance(override["default"], str):
        base["default"] = normalize_action(override["default"])
    if "tools" in override and isinstance(override["tools"], dict):
        for t, act in override["tools"].items():
            if isinstance(act, str):
                base["tools"][t.lower()] = normalize_action(act)
