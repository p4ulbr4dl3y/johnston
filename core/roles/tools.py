"""Tool filtering and hardening applied to a role's subagent tools."""

import copy

from core.defaults.tools import SUBAGENT_EXCLUDED_TOOLS

HARDENED_SHELL_DESCRIPTION = (
    "Run a synchronous terminal command with a configurable timeout (default 60s, max 300s). "
    "Processes terminate on timeout. Always use non-interactive flags (e.g. -y, --non-interactive) to prevent hanging."
)


def apply_role_tools(subagent, definition) -> None:
    """Filter the subagent's tools by role and harden the shell description.

    Disables nested subagent spawning, background task management, UI questions,
    and applies the role's read-only/allowed/disallowed lists. The shell tool's
    description is replaced with a non-interactive, timeout-bound variant.
    """
    subagent.allow_task = False
    subagent.tools = [
        t
        for t in (getattr(subagent, "tools", None) or [])
        if t.get("function", {}).get("name", "").lower() not in SUBAGENT_EXCLUDED_TOOLS
    ]

    read_only = getattr(definition, "read_only", False)
    disallowed = getattr(definition, "disallowed_tools", None)
    allowed = getattr(definition, "allowed_tools", None)
    if read_only or disallowed or allowed:
        subagent.tools = [
            t for t in subagent.tools if definition.is_tool_allowed(t.get("function", {}).get("name", "")) is None
        ]

    subagent.tools = [_rebuild_tool(t) for t in subagent.tools]


def _rebuild_tool(t) -> dict:
    if isinstance(t, dict) and t.get("function", {}).get("name") == "shell":
        t_copy = copy.deepcopy(t)
        t_copy["function"]["description"] = HARDENED_SHELL_DESCRIPTION
        return t_copy
    return t
