import json
from typing import Any, Dict, List, Tuple

from core.application.generation.prompt_builder import PromptBuilder
from core.infrastructure.runtime.token_util import estimate_tokens
from core.infrastructure.runtime.tool_name import normalize_tool_name
from core.models_catalog import catalog

# Sentinel for the _tool_policy_error memo so a cached "allowed" (None) result
# is indistinguishable from "not yet cached".
_MISSING = object()



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

        # Cross-call memo keyed by (role identity, canonical tool name) so the
        # agent loop doesn't re-evaluate the role policy for the same tool on
        # every tool_result of a multi-tool turn.
        try:
            role_key = id(mode_def)
        except Exception:
            role_key = repr(mode_def)
        key = (role_key, tool_name or "")
        cache = getattr(self, "_tool_policy_cache", None)
        if cache is None:
            cache = {}
            self._tool_policy_cache = cache
        cached = cache.get(key, _MISSING)
        if cached is not _MISSING:
            return cached

        clean_name = self._canonical_tool_name(tool_name).lower()
        result = role_tool_error(mode_def, clean_name)
        cache[key] = result
        if len(cache) > 256:
            # Bounded cache: drop the oldest entries by order of insertion.
            for _ in range(64):
                if cache:
                    cache.pop(next(iter(cache)))
        return result


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
    all_tools = builder.build_tools()
    sys_tokens = estimate_tokens(sys_prompt) + estimate_tokens(all_tools)
    return sys_prompt, all_tools, sys_tokens


async def build_prompt_context_async(agent: Any) -> Tuple[str, List[Dict[str, Any]], int]:
    """Async variant of ``build_prompt_context`` for the async agent loop.

    Uses the async system-prompt build so cache-miss file reads (project
    instructions, rules, skills scan) go to a worker thread and never block the
    event loop. Tool schema building stays unchanged.
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
    sys_prompt = await builder.build_system_prompt_async()
    all_tools = builder.build_tools()
    sys_tokens = estimate_tokens(sys_prompt) + estimate_tokens(all_tools)
    return sys_prompt, all_tools, sys_tokens
