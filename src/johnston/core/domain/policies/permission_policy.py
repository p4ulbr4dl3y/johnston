"""Permission policy: enums, baselines, and re-exports.

Internal helpers for shell parsing, pattern matching, rule evaluation,
workspace boundaries, and secrets handling live in the ``policy_*``
child modules and are re-exported here for backwards compatibility.
"""
import os
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict

try:
    from johnston.core.infrastructure.platform.paths import LOGS_DIR, SECRETS_FILE
except Exception:
    _cfg = os.environ.get("JOHNSTON_CONFIG_DIR") or os.path.expanduser("~/.johnston")
    LOGS_DIR = os.path.join(_cfg, "logs")
    SECRETS_FILE = os.path.join(_cfg, "secrets.json")

READ_ONLY_TOOLS = frozenset({"read", "view_file", "search"})


class PermissionAction(str, Enum):
    """Outcome of a tool permission check."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


VALID_ACTIONS = frozenset(action.value for action in PermissionAction)


class ExecutionMode(str, Enum):
    """Execution / Approval Mode for tool authorization."""

    REVIEW = "review"
    EDITS = "edits"
    YOLO = "yolo"


VALID_EXECUTION_MODES = frozenset(mode.value for mode in ExecutionMode)

MODE_TOOL_BASELINES: Dict[ExecutionMode, Dict[str, PermissionAction]] = {
    ExecutionMode.REVIEW: {
        "create": PermissionAction.ASK,
        "edit": PermissionAction.ASK,
        "shell": PermissionAction.ASK,
        "web_fetch": PermissionAction.ASK,
        "_mcp": PermissionAction.ASK,
        "default": PermissionAction.ALLOW,
    },
    ExecutionMode.EDITS: {
        "create": PermissionAction.ALLOW,
        "edit": PermissionAction.ALLOW,
        "shell": PermissionAction.ASK,
        "web_fetch": PermissionAction.ALLOW,
        "_mcp": PermissionAction.ASK,
        "default": PermissionAction.ALLOW,
    },
    ExecutionMode.YOLO: {
        "create": PermissionAction.ALLOW,
        "edit": PermissionAction.ALLOW,
        "shell": PermissionAction.ALLOW,
        "web_fetch": PermissionAction.ALLOW,
        "_mcp": PermissionAction.ALLOW,
        "default": PermissionAction.ALLOW,
    },
}


def normalize_execution_mode(mode: Any, default: ExecutionMode = ExecutionMode.REVIEW) -> ExecutionMode:
    """Normalizes an execution mode to ExecutionMode enum. Invalid values fallback to default."""
    if isinstance(mode, ExecutionMode):
        return mode
    if isinstance(mode, str):
        cleaned = mode.strip().lower()
        if cleaned == "edits":
            return ExecutionMode.EDITS
        if cleaned == "yolo":
            return ExecutionMode.YOLO
        if cleaned == "review":
            return ExecutionMode.REVIEW
    return default


def get_mode_baseline_action(
    mode: ExecutionMode,
    tool_name: str,
    is_mcp: bool = False,
) -> PermissionAction:
    """Returns the baseline action for a given tool under the specified execution mode."""
    canonical = (tool_name or "").strip().lower()
    table = MODE_TOOL_BASELINES.get(mode, MODE_TOOL_BASELINES[ExecutionMode.REVIEW])
    if is_mcp:
        return table.get("_mcp", table.get("default", PermissionAction.ALLOW))
    if canonical in table:
        return table[canonical]
    return table.get("default", PermissionAction.ALLOW)


@dataclass(frozen=True)
class PermissionDecision:
    """Result of a tool permission check: the action and a human-readable reason."""

    action: PermissionAction
    reason: str


# Builtin tools that are NOT covered by an explicit config entry fall back to
# the configured default action (ask/deny). MCP tools (not in this set) default
# to 'allow'. Used as the fallback when no builtin_tool_names frozenset is
# injected via DI.
BUILTIN_TOOLS = frozenset(
    {
        "read",
        "create",
        "edit",
        "shell",
        "search",
        "ask_user",
        "web_fetch",
        "invoke_subagent",
        "message_subagent",
        "kill",
        "update_plan",
        "view_file",
    }
)

from johnston.core.domain.policies.policy_eval import evaluate_pattern_rules  # noqa: E402, F401  (re-exported)
from johnston.core.domain.policies.policy_matching import (  # noqa: E402, F401  (re-exported)
    PATH_ARG_KEYS,
    extract_tool_target_value,
    extract_tool_target_values,
    match_path_pattern,
    match_pattern,
    suggest_pattern,
)
from johnston.core.domain.policies.policy_secrets import (  # noqa: E402, F401  (re-exported)
    get_secrets_file,
    get_secrets_files,
    get_trusted_read_roots,
    is_secrets_file,
    is_secrets_shell_command,
)
from johnston.core.domain.policies.policy_shell import (  # noqa: E402, F401  (re-exported)
    _MULTI_COMMAND_TOOLS,
    _UNSAFE_SHELL_REGEX,
    _WRAPPER_COMMANDS,
    extract_command_signature,
    extract_shell_subcommands,
    has_unsafe_shell_syntax,
    normalize_action,
)
from johnston.core.domain.policies.policy_workspace import (  # noqa: E402, F401  (re-exported)
    evaluate_workspace_boundary,
    is_path_within_workspace,
    merge_perms,
)


def get_config_dir() -> str:
    """Returns the Johnston configuration directory path."""
    try:
        from johnston.core.infrastructure.platform import paths

        cd = getattr(paths, "CONFIG_DIR", None)
        if cd:
            return str(cd)
    except Exception:
        pass
    return os.environ.get("JOHNSTON_CONFIG_DIR") or os.path.expanduser("~/.johnston")
