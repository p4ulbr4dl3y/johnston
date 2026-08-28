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

    async def _normalize_tool_result(self, result: Any) -> Any:
        """Normalize a raw tool result into a :class:`ToolResult`.

        Thin delegation to the shared domain-level normalizer so the registry,
        MCP adapter path and agent loop can never drift apart.
        """
        from core.domain.defaults.errors import normalize_tool_result

        return await normalize_tool_result(result)

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

    def _is_tool_concurrency_safe(self, tool_name: str, args: dict | None = None) -> bool:
        from core.domain.ports.tool_registry import get_default_tool_registry

        reg = get_default_tool_registry()
        if reg is not None and hasattr(reg, "is_tool_concurrency_safe"):
            try:
                return bool(reg.is_tool_concurrency_safe(tool_name, args))
            except Exception:
                return False
        return False



async def build_prompt_context_async(agent: Any) -> Tuple[str, List[Dict[str, Any]], int]:
    """Builds system prompt + tool schema for an agent asynchronously and returns them with token count.

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
    app = getattr(agent, "app", None)
    sandbox_val = getattr(agent, "sandbox_enabled", None)
    if sandbox_val is None and app:
        sandbox_val = getattr(app, "sandbox_enabled", None)
    if sandbox_val is None:
        if agent_role == "explorer" or getattr(agent, "read_only", False):
            sandbox_val = True

    builder = PromptBuilder(
        agent.system_prompt,
        agent.tools,
        role=agent_role,
        allow_task=allow_task,
        model_name=m_name,
        cwd=getattr(agent, "cwd", None),
        is_subagent=is_subagent,
        subagent_schema=getattr(agent, "subagent_schema", None),
        sandbox_enabled=sandbox_val,
        worktree_branch=getattr(agent, "worktree_branch", None),
    )
    sys_prompt = await builder.build_system_prompt_async()
    all_tools = builder.build_tools()
    sys_tokens = estimate_tokens(sys_prompt) + estimate_tokens(all_tools)
    return sys_prompt, all_tools, sys_tokens
