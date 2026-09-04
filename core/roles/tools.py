"""Tool filtering and hardening applied to a role's subagent tools."""

import copy
from typing import Any

from core.domain.policies.role_policy import AgentRole, role_tool_error

HARDENED_SHELL_DESCRIPTION = (
    "Run a synchronous terminal command with a configurable timeout (default 120s, max 600s). "
    "Processes terminate on timeout. Always use non-interactive flags (e.g. -y, --non-interactive) to prevent hanging."
)


def apply_role_tools(subagent: Any, definition: AgentRole) -> None:
    """Filter the subagent's tools by role and harden the shell description.

    Disables nested subagent spawning, background task management, UI questions,
    and applies the role's read-only/allowed/disallowed lists. The shell tool's
    description is replaced with a non-interactive, timeout-bound variant and
    background execution is stripped. Uses the same single role-tool policy
    (``role_tool_error`` with ``is_subagent=True``) as prompt_builder and the
    role registry.
    """
    subagent.allow_task = False
    subagent.tools = [
        t
        for t in (getattr(subagent, "tools", None) or [])
        if role_tool_error(definition, t.get("function", {}).get("name", ""), is_subagent=True) is None
    ]
    subagent.tools = [_rebuild_tool(t) for t in subagent.tools]


def _rebuild_tool(t) -> dict:
    if isinstance(t, dict) and t.get("function", {}).get("name") == "shell":
        t_copy = copy.deepcopy(t)
        t_copy["function"]["description"] = HARDENED_SHELL_DESCRIPTION
        params = t_copy.get("function", {}).get("parameters", {})
        if isinstance(params, dict) and "properties" in params and isinstance(params["properties"], dict):
            params["properties"].pop("wait_seconds", None)
            if "timeout" in params["properties"] and isinstance(params["properties"]["timeout"], dict):
                params["properties"]["timeout"]["description"] = (
                    "Seconds before SIGTERM (defaults to 120s, max 600s)."
                )
        return t_copy
    return t
