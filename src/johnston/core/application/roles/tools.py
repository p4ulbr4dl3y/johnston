"""Tool filtering and hardening applied to a role's subagent tools."""

import copy
from typing import Any, Optional

from johnston.core.domain.policies.role_policy import AgentMode, AgentRole, role_tool_error

HARDENED_SHELL_DESCRIPTION = (
    "Run a synchronous terminal command with a configurable timeout (default 120s, max 600s). "
    "Processes terminate on timeout. Always use non-interactive flags (e.g. -y, --non-interactive) to prevent hanging."
)


def apply_role_tools(
    agent: Any,
    definition: AgentRole,
    is_subagent: bool = True,
    mode: Optional[AgentMode] = None,
) -> None:
    """Filter the agent's tools by role and harden tools for non-interactive execution.

    For non-interactive modes (subagents and headless): disables nested subagent
    spawning, background task management, UI questions, and applies the role's
    read-only/allowed/disallowed lists. The shell tool's description is replaced
    with a non-interactive, timeout-bound variant and background execution is stripped.
    For interactive agents: applies allowed/disallowed lists while preserving interactive capabilities.
    """
    raw_tools = getattr(agent, "tools", None)
    if not raw_tools and callable(getattr(agent, "default_tools_provider", None)):
        raw_tools = agent.default_tools_provider()
    raw_tools = raw_tools or []

    if mode is not None:
        effective_mode = AgentMode(mode.lower().strip()) if isinstance(mode, str) else mode
    else:
        agent_mode = getattr(agent, "mode", None)
        if isinstance(agent_mode, AgentMode):
            effective_mode = agent_mode
        elif isinstance(agent_mode, str):
            try:
                effective_mode = AgentMode(agent_mode.lower().strip())
            except ValueError:
                effective_mode = AgentMode.SUBAGENT if is_subagent else AgentMode.INTERACTIVE
        else:
            effective_mode = AgentMode.SUBAGENT if is_subagent else AgentMode.INTERACTIVE
    if not effective_mode.is_interactive:
        agent.allow_task = False
        filtered = [
            t
            for t in raw_tools
            if role_tool_error(definition, t.get("function", {}).get("name", ""), mode=effective_mode) is None
        ]
        agent.tools = [_rebuild_tool(t) for t in filtered]
    else:
        agent.allow_task = getattr(agent, "allow_task", True)
        agent.tools = [
            t
            for t in raw_tools
            if role_tool_error(definition, t.get("function", {}).get("name", ""), mode=effective_mode) is None
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
