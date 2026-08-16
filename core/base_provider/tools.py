import json
from typing import Any, Dict, List, Tuple

from core.application.generation.prompt_builder import PromptBuilder
from core.infrastructure.runtime.token_util import estimate_tokens
from core.infrastructure.runtime.tool_name import normalize_tool_name
from core.models_catalog import catalog


class ToolMixin:
    """Mixin providing tool-name canonicalization and runtime tool-policy checks for BaseAgent."""

    def _canonical_tool_name(self, tool_name: str) -> str:
        normalizer = getattr(self, "tool_name_normalizer", None)
        if normalizer:
            return normalizer(tool_name or "")
        return normalize_tool_name(tool_name)

    def _normalize_tool_result(self, result: Any) -> Any:
        """Normalize a raw tool result into a :class:`ToolResult`.

        Accepts ``ToolResult`` (returned as-is), a raw ``ERR:`` string (kept
        verbatim and marked as an explicit error), a dict/list (JSON-serialized
        so the model message stays a string), ``None`` -> empty, and any other
        value -> ``str()``. Guarantees a plain string ``content`` for the model.
        """
        from core.domain.defaults.errors import ToolResult, ToolResultStatus

        if isinstance(result, ToolResult):
            return result
        if result is None:
            return ToolResult.done("")
        if isinstance(result, (dict, list)):
            return ToolResult.done(json.dumps(result, ensure_ascii=False))
        text = str(result)
        if text.lstrip().lower().startswith("err:"):
            return ToolResult(content=text, status=ToolResultStatus.ERROR)
        return ToolResult.done(text)

    def _tool_policy_error(self, tool_name: str, mode_def: Any) -> Any:
        from core.domain.policies.role_policy import role_tool_error

        clean_name = self._canonical_tool_name(tool_name).lower()
        return role_tool_error(mode_def, clean_name)


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
        subagent_schema=getattr(agent, "subagent_schema", None),
    )
    sys_prompt = builder.build_system_prompt()
    all_tools = builder.build_tools(provider_key=getattr(agent, "provider_key", ""))
    sys_tokens = estimate_tokens(sys_prompt) + estimate_tokens(all_tools)
    return sys_prompt, all_tools, sys_tokens
