"""Pure permission policy helpers (no state, no IO)."""

from typing import Any, Dict

VALID_ACTIONS = {"allow", "ask", "deny"}

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
        "replace_file_content",
        "multi_replace_file_content",
        "write_to_file",
        "glob",
        "grep",
        "list",
        "shell",
        "ask_user",
        "web_fetch",
        "web_search",
        "invoke_subagent",
        "manage_subagent",
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
