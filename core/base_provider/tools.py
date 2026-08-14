import uuid
from typing import Any, Dict, List, Optional, Tuple

from core.infrastructure.runtime.token_util import estimate_tokens
from core.models_catalog import catalog
from core.prompt_builder import PromptBuilder


class ToolMixin:
    """Mixin providing tool-name canonicalization and runtime tool-policy checks for BaseAgent."""

    def _canonical_tool_name(self, tool_name: str) -> str:
        from tools.registry import normalize_tool_name

        return normalize_tool_name(tool_name or "")

    def _tool_policy_error(self, tool_name: str, mode_def: Any) -> str | None:
        from core.role_registry import role_tool_error

        clean_name = self._canonical_tool_name(tool_name).lower()
        return role_tool_error(mode_def, clean_name)


def new_tool_call_id(idx: Optional[int] = None) -> str:
    """Returns a unique tool-call id, derived from a stream index or generated."""
    if idx is None:
        return f"call_{uuid.uuid4().hex[:8]}"
    return f"call_{idx}"


def build_prompt_context(agent: Any) -> Tuple[str, List[Dict[str, Any]], int]:
    """Builds system prompt + tool schema for an agent and returns them with their token count.

    Shared by the agent loop (stream_steps) and the compaction path (compact_history)
    so the PromptBuilder wiring is not duplicated across both call sites.
    """
    agent_role = getattr(agent, "role", "worker")
    allow_task = getattr(agent, "allow_task", True)
    m_name = (
        catalog.get_model_display_name(getattr(agent, "provider_key", ""), getattr(agent, "model", ""))
        or getattr(agent, "model", "")
    )
    is_subagent = getattr(agent, "is_subagent", False)
    builder = PromptBuilder(
        agent.system_prompt,
        agent.tools,
        role=agent_role,
        allow_task=allow_task,
        model_name=m_name,
        cwd=getattr(agent, "cwd", None),
        is_subagent=is_subagent,
    )
    sys_prompt = builder.build_system_prompt()
    all_tools = builder.build_tools(provider_key=getattr(agent, "provider_key", ""))
    sys_tokens = estimate_tokens(sys_prompt) + estimate_tokens(all_tools)
    return sys_prompt, all_tools, sys_tokens
