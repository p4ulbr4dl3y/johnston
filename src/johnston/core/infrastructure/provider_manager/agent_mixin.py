import logging
from typing import Any, List, Optional

from johnston.core.domain.ports.tool_registry import ToolRegistryPort, get_default_tool_registry
from johnston.core.infrastructure.config.settings import get_settings

logger = logging.getLogger(__name__)


class ProviderManagerAgentMixin:
    _tool_registry: Optional[ToolRegistryPort]

    def create_agent_for_provider(
        self, provider_key: str, tool_registry: Optional[ToolRegistryPort] = None
    ):
        pdef = self.load_provider_def(provider_key)
        if pdef is None:
            return None
        if not pdef.enabled:
            logger.warning("Refusing to create agent for disabled provider: %s", provider_key)
            return None
        pkey_str = pdef.key
        stored_key = self.get_api_key(pkey_str)
        model_val = self.get_provider_model(provider_key)
        thinking_effort = self.get_provider_thinking_effort(provider_key, model_val)

        from johnston.core.base_provider import BaseAgent
        from johnston.core.infrastructure.runtime.tool_name import normalize_tool_name

        reg = tool_registry or getattr(self, "_tool_registry", None) or get_default_tool_registry()
        tool_executor = reg.execute_tool if reg is not None else None
        default_tools_provider = reg.get_default_tools if reg is not None else None
        image_processor = reg.process_image_file if reg is not None else None
        subagent_schema = reg.get_subagent_schema() if reg is not None else None

        agent = BaseAgent(
            api_key=stored_key or pdef.api_key,
            model=model_val,
            base_url=pdef.base_url,
            provider_key=pkey_str,
            api_type=pdef.api_type,
            headers=pdef.headers,
            extra_body=pdef.extra_body,
            reasoning_effort=pdef.reasoning_effort,
            thinking_effort=thinking_effort,
            chunk_timeout=pdef.chunk_timeout,
            max_tokens=pdef.max_tokens or get_settings().llm.default_max_tokens,
            max_retries=pdef.max_retries,
            retry_delay=pdef.retry_delay,
            retry_backoff=pdef.retry_backoff,
            max_retry_delay=pdef.max_retry_delay,
            tool_executor=tool_executor,
            default_tools_provider=default_tools_provider,
            image_processor=image_processor,
            tool_name_normalizer=normalize_tool_name,
        )
        if subagent_schema is not None:
            agent.subagent_schema = subagent_schema
        return agent

    def create_active_agent(self):
        active_key = self.get_active_provider_key()
        if not active_key:
            return None
        return self.create_agent_for_provider(active_key)

    def recreate_active_agent(
        self,
        provider_key: Optional[str] = None,
        history: Optional[List[Any]] = None,
        role: Optional[str] = None,
    ) -> Any:
        """Recreates active agent preserving history and role."""
        if provider_key:
            self.set_active_provider_key(provider_key)
        agent = self.create_active_agent()
        if agent is not None:
            if history is not None:
                agent.history = list(history)
            if role is not None:
                agent.role = role
        return agent
