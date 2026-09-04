"""Tool filtering and hardening applied to a role's subagent tools."""

import copy
from typing import Any

from core.domain.policies.role_policy import AgentRole, role_tool_error

HARDENED_SHELL_DESCRIPTION = (
    "Run a synchronous terminal command with a configurable timeout (default 120s, max 600s). "
    "Processes terminate on timeout. Always use non-interactive flags (e.g. -y, --non-interactive) to prevent hanging."
)


def apply_role_tools(agent: Any, definition: AgentRole, is_subagent: bool = True) -> None:
    """Filter the agent's tools by role and harden tools for subagents.

    For subagents: disables nested subagent spawning, background task management, UI questions,
    and applies the role's read-only/allowed/disallowed lists. The shell tool's description
    is replaced with a non-interactive, timeout-bound variant and background execution is stripped.
    For main agents: applies allowed/disallowed lists while preserving interactive capabilities.
    """
    raw_tools = getattr(agent, "tools", None)
    if not raw_tools and callable(getattr(agent, "default_tools_provider", None)):
        raw_tools = agent.default_tools_provider()
    raw_tools = raw_tools or []

    if is_subagent:
        agent.allow_task = False
        filtered = [
            t
            for t in raw_tools
            if role_tool_error(definition, t.get("function", {}).get("name", ""), is_subagent=True) is None
        ]
        agent.tools = [_rebuild_tool(t) for t in filtered]
    else:
        agent.allow_task = getattr(agent, "allow_task", True)
        agent.tools = [
            t
            for t in raw_tools
            if role_tool_error(definition, t.get("function", {}).get("name", ""), is_subagent=False) is None
        ]



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
